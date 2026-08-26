"""Provider webhooks. All routes are workspace-scoped by slug, signature-
verified (fail closed), idempotent via the WebhookEvent ledger, and enqueue
side effects instead of performing them inline — handlers return fast."""
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db import get_db
from engine.models import Message, Prospect, WebhookEvent, Workspace
from engine.queue import enqueue
from engine.ratelimit import check_public_rate
from engine.services.booking import record_booking_event
from engine.services.credentials import get_credentials
from engine.services.smser import send_sms
from engine.services.suppression import (
    normalize_phone,
    suppress,
    unsuppress,
)
from engine.webhooks.verify import (
    verify_calcom,
    verify_svix,
    verify_twilio,
    verify_url_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()

OPT_OUT_COMMANDS = {"STOP", "UNSUB", "UNSUBSCRIBE", "QUIT", "CANCEL"}


async def _workspace_by_slug(db: AsyncSession, slug: str) -> Workspace:
    row = await db.execute(select(Workspace).where(Workspace.slug == slug))
    workspace = row.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace")
    return workspace


async def _claim_event(db: AsyncSession, provider: str, external_id: str) -> bool:
    """True if this event is new; False if it was already processed.
    Uses a SAVEPOINT so a duplicate never rolls back work already done in
    the caller's transaction."""
    if not external_id:
        return True  # nothing to dedup on — process it
    try:
        async with db.begin_nested():
            db.add(WebhookEvent(provider=provider, external_id=external_id))
            await db.flush()
        return True
    except IntegrityError:
        return False


def _body_fingerprint(*parts: str) -> str:
    """Deterministic external id for providers that omit an event id, so
    replays still dedup instead of degrading open."""
    import hashlib

    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:64]


async def _prospect_by_email(
    db: AsyncSession, workspace_id: str, email: str
) -> Prospect | None:
    row = await db.execute(
        select(Prospect).where(
            Prospect.workspace_id == workspace_id,
            Prospect.email == email.lower().strip(),
        )
    )
    return row.scalar_one_or_none()


# ── Resend (email delivery events + inbound replies) ─────────────────


@router.post("/webhooks/{slug}/resend")
async def resend_webhook(
    slug: str,
    request: Request,
    svix_id: str | None = Header(default=None),
    svix_timestamp: str | None = Header(default=None),
    svix_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _workspace_by_slug(db, slug)
    payload = await request.body()
    creds = await get_credentials(db, workspace.id, "resend") or {}
    verify_svix(
        creds.get("webhook_secret"), svix_id, svix_timestamp, svix_signature, payload
    )

    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    event_type = str(event.get("type", ""))
    data = event.get("data", {}) or {}

    external_id = svix_id or f"{event_type}:{data.get('email_id', '')}"
    if not await _claim_event(db, "resend", external_id):
        return {"received": True, "duplicate": True}

    status_map = {
        "email.delivered": "delivered",
        "email.opened": "opened",
        "email.clicked": "clicked",
        "email.bounced": "bounced",
        "email.complained": "complained",
    }
    if event_type in status_map:
        email_id = data.get("email_id")
        if email_id:
            row = await db.execute(
                select(Message).where(
                    Message.workspace_id == workspace.id,
                    Message.provider_message_id == email_id,
                )
            )
            message = row.scalar_one_or_none()
            if message is not None:
                message.status = status_map[event_type]
        if event_type in ("email.bounced", "email.complained"):
            reason = "bounce" if event_type == "email.bounced" else "complaint"
            for addr in data.get("to") or []:
                await suppress(db, workspace.id, "email", addr, reason)
        return {"received": True}

    if event_type in ("email.received", "inbound_email"):
        from_addr = str(data.get("from", "")).lower().strip()
        text = str(data.get("text", "") or "")[:5000]
        prospect = await _prospect_by_email(db, workspace.id, from_addr)
        if prospect is None:
            logger.info("Inbound email from unknown sender %s; ignored", from_addr)
            return {"received": True}
        inbound = Message(
            workspace_id=workspace.id,
            prospect_id=prospect.id,
            channel="email",
            direction="in",
            subject=str(data.get("subject", ""))[:500],
            body=text,
        )
        db.add(inbound)
        await db.flush()
        await enqueue(
            db,
            "inbound_message",
            {
                "workspace_id": workspace.id,
                "prospect_id": prospect.id,
                "channel": "email",
                "text": text,
                "message_id": inbound.id,
            },
            workspace_id=workspace.id,
            idempotency_key=f"inbound:{inbound.id}",
        )
    return {"received": True}


# ── Africa's Talking (inbound SMS) ───────────────────────────────────


@router.post("/webhooks/{slug}/sms/{token}")
async def sms_webhook(
    slug: str,
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _workspace_by_slug(db, slug)
    creds = await get_credentials(db, workspace.id, "africastalking") or {}
    verify_url_token(creds.get("webhook_token"), token)

    form = await request.form()
    text = str(form.get("text", "")).strip()
    phone = normalize_phone(str(form.get("from", "")))
    at_id = str(form.get("id", ""))
    if not phone:
        return {"status": "ignored"}
    if not at_id:
        # AT omitted the id — fall back to a content fingerprint so a
        # replay still dedups instead of enqueuing duplicate replies.
        at_id = _body_fingerprint(
            slug, phone, text, str(form.get("date", "")), str(form.get("to", ""))
        )
    if not await _claim_event(db, "africastalking", at_id):
        return {"status": "duplicate"}

    command = text.upper().strip()

    # Compliance commands are handled synchronously, before anything else.
    if command in OPT_OUT_COMMANDS:
        await suppress(db, workspace.id, "sms", phone, "opt_out")
        row = await db.execute(
            select(Prospect).where(
                Prospect.workspace_id == workspace.id, Prospect.phone == phone
            )
        )
        for prospect in row.scalars().all():
            prospect.stage = "opted_out"
            prospect.next_followup_at = None
        try:
            await send_sms(
                db, workspace, None, to_phone=phone,
                body="You have been unsubscribed. Reply START to resubscribe.",
                skip_policy_checks=True,
            )
        except Exception as exc:  # noqa: BLE001 — confirmation is best-effort
            logger.warning("Opt-out confirmation failed for %s: %s", phone, exc)
        return {"status": "opted_out"}

    if command == "START":
        await unsuppress(db, workspace.id, "sms", phone)
        try:
            await send_sms(
                db, workspace, None, to_phone=phone,
                body="You have been resubscribed. Reply STOP at any time to opt out.",
                skip_policy_checks=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Resubscribe confirmation failed for %s: %s", phone, exc)
        return {"status": "resubscribed"}

    if command == "HELP":
        support = (workspace.playbook or {}).get("support_contact", "")
        try:
            await send_sms(
                db, workspace, None, to_phone=phone,
                body=f"Reply STOP to unsubscribe. {('Contact ' + support) if support else ''}".strip(),
                skip_policy_checks=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("HELP reply failed for %s: %s", phone, exc)
        return {"status": "help_sent"}

    row = await db.execute(
        select(Prospect).where(
            Prospect.workspace_id == workspace.id, Prospect.phone == phone
        )
    )
    prospect = row.scalars().first()
    if prospect is None:
        logger.info("Inbound SMS from unknown number; ignored")
        return {"status": "unknown_sender"}

    inbound = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        channel="sms",
        direction="in",
        body=text[:2000],
    )
    db.add(inbound)
    await db.flush()
    await enqueue(
        db,
        "inbound_message",
        {
            "workspace_id": workspace.id,
            "prospect_id": prospect.id,
            "channel": "sms",
            "text": text[:2000],
            "message_id": inbound.id,
        },
        workspace_id=workspace.id,
        idempotency_key=f"inbound:{inbound.id}",
    )
    return {"status": "queued"}


# ── Twilio WhatsApp (inbound conversation) ───────────────────────────


@router.post("/webhooks/{slug}/whatsapp")
async def whatsapp_webhook(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Inbound WhatsApp via Twilio. Same compliance-first shape as SMS:
    STOP/START/HELP handled synchronously, everything else queued for the
    reply agent (which answers on WhatsApp inside the 24h service window)."""
    from engine.services.whatsapp import send_whatsapp

    workspace = await _workspace_by_slug(db, slug)
    form = {k: str(v) for k, v in (await request.form()).items()}
    creds = await get_credentials(db, workspace.id, "twilio") or {}
    verify_twilio(
        creds.get("auth_token"),
        request.headers.get("X-Twilio-Signature"),
        str(request.url),
        form,
    )

    text = form.get("Body", "").strip()
    phone = normalize_phone(form.get("From", "").removeprefix("whatsapp:"))
    sid = form.get("MessageSid", "")
    if not phone:
        return {"status": "ignored"}
    if not sid:
        sid = _body_fingerprint(slug, phone, text, form.get("To", ""))
    if not await _claim_event(db, "twilio_whatsapp", sid):
        return {"status": "duplicate"}

    command = text.upper().strip()
    if command in OPT_OUT_COMMANDS:
        await suppress(db, workspace.id, "whatsapp", phone, "opt_out")
        try:
            await send_whatsapp(
                db, workspace, None, to_phone=phone,
                body="You have been unsubscribed. Reply START to resubscribe.",
                skip_policy_checks=True,
            )
        except Exception as exc:  # noqa: BLE001 — confirmation is best-effort
            logger.warning("WhatsApp opt-out confirmation failed: %s", exc)
        return {"status": "opted_out"}
    if command == "START":
        await unsuppress(db, workspace.id, "whatsapp", phone)
        return {"status": "resubscribed"}
    if command == "HELP":
        support = (workspace.playbook or {}).get("support_contact", "")
        try:
            await send_whatsapp(
                db, workspace, None, to_phone=phone,
                body=f"Reply STOP to unsubscribe. {('Contact ' + support) if support else ''}".strip(),
                skip_policy_checks=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WhatsApp HELP reply failed: %s", exc)
        return {"status": "help_sent"}

    row = await db.execute(
        select(Prospect).where(
            Prospect.workspace_id == workspace.id, Prospect.phone == phone
        )
    )
    prospect = row.scalars().first()
    if prospect is None:
        logger.info("Inbound WhatsApp from unknown number; ignored")
        return {"status": "unknown_sender"}

    inbound = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        channel="whatsapp",
        direction="in",
        body=text[:2000],
    )
    db.add(inbound)
    await db.flush()
    await enqueue(
        db,
        "inbound_message",
        {
            "workspace_id": workspace.id,
            "prospect_id": prospect.id,
            "channel": "whatsapp",
            "text": text[:2000],
            "message_id": inbound.id,
        },
        workspace_id=workspace.id,
        idempotency_key=f"inbound:{inbound.id}",
    )
    return {"status": "queued"}


# ── Cal.com (booking lifecycle) ──────────────────────────────────────


@router.post("/webhooks/{slug}/calcom")
async def calcom_webhook(
    slug: str,
    request: Request,
    x_cal_signature_256: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _workspace_by_slug(db, slug)
    payload = await request.body()
    creds = await get_credentials(db, workspace.id, "calcom") or {}
    verify_calcom(creds.get("webhook_secret"), x_cal_signature_256, payload)

    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    trigger = str(event.get("triggerEvent", ""))
    booking_payload = event.get("payload", {}) or {}
    uid = str(booking_payload.get("uid", ""))

    if not await _claim_event(db, "calcom", f"{trigger}:{uid}"):
        return {"received": True, "duplicate": True}

    booking = await record_booking_event(db, workspace, trigger, booking_payload)
    if booking and booking.prospect_id and trigger == "BOOKING_CREATED":
        await enqueue(
            db,
            "hubspot_mark_booked",
            {
                "workspace_id": workspace.id,
                "prospect_id": booking.prospect_id,
                "booking_uid": booking.provider_uid,
                "booking_time": str(booking_payload.get("startTime", "")),
            },
            workspace_id=workspace.id,
            idempotency_key=f"hs_booked:{booking.provider_uid}",
        )
    return {"received": True}


# ── Twilio Voice (IVR) ───────────────────────────────────────────────


async def _verify_twilio_request(
    db: AsyncSession, workspace: Workspace, request: Request, form: dict
) -> None:
    creds = await get_credentials(db, workspace.id, "twilio") or {}
    verify_twilio(
        creds.get("auth_token"),
        request.headers.get("X-Twilio-Signature"),
        str(request.url),
        form,
    )


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


@router.post("/webhooks/{slug}/voice")
async def voice_twiml(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    workspace = await _workspace_by_slug(db, slug)
    form = {k: str(v) for k, v in (await request.form()).items()}
    await _verify_twilio_request(db, workspace, request, form)

    pb = workspace.playbook or {}
    company = _escape_xml(pb.get("company_name", workspace.name))
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Hi, this is the scheduling assistant from {company}.
    You recently replied to our outreach.
    Press 1 to talk to our team now, or press 2 and we will send a
    calendar link to schedule instead.
  </Say>
  <Gather numDigits="1" action="/webhooks/{slug}/voice/gather" method="POST" timeout="10"/>
  <Say voice="Polly.Joanna">We didn't catch your input. We'll follow up by email. Goodbye.</Say>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/{slug}/voice/gather")
async def voice_gather(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    workspace = await _workspace_by_slug(db, slug)
    form = {k: str(v) for k, v in (await request.form()).items()}
    await _verify_twilio_request(db, workspace, request, form)

    creds = await get_credentials(db, workspace.id, "twilio") or {}
    sales_phone = creds.get("sales_phone", "")
    if form.get("Digits") == "1" and sales_phone:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">Connecting you now.</Say>
  <Dial><Number>{_escape_xml(sales_phone)}</Number></Dial>
</Response>"""
    else:
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">No problem. We'll send a calendar link by email. Goodbye.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/{slug}/voice/status")
async def voice_status(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    workspace = await _workspace_by_slug(db, slug)
    form = {k: str(v) for k, v in (await request.form()).items()}
    await _verify_twilio_request(db, workspace, request, form)
    logger.info(
        "Call completed | ws=%s sid=%s status=%s duration=%ss",
        workspace.id, form.get("CallSid"), form.get("CallStatus"),
        form.get("CallDuration", "0"),
    )
    return {"received": True}


# ── Public unsubscribe page ──────────────────────────────────────────


async def _prospect_by_token(db: AsyncSession, token: str) -> Prospect:
    row = await db.execute(
        select(Prospect).where(Prospect.unsubscribe_token == token)
    )
    prospect = row.scalar_one_or_none()
    if prospect is None:
        raise HTTPException(status_code=404, detail="Unknown link")
    return prospect


async def _apply_unsubscribe(db: AsyncSession, prospect: Prospect) -> None:
    await suppress(db, prospect.workspace_id, "email", prospect.email, "opt_out")
    if prospect.phone:
        await suppress(db, prospect.workspace_id, "sms", prospect.phone, "opt_out")
        await suppress(
            db, prospect.workspace_id, "whatsapp", prospect.phone, "opt_out"
        )
    prospect.stage = "opted_out"
    prospect.next_followup_at = None


_UNSUB_STYLE = (
    "font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center"
)


@router.get("/u/{token}", response_class=HTMLResponse)
async def unsubscribe_page(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Confirmation page only — the write happens on POST. Mail scanners and
    link prefetchers GET every URL in an email; a bare GET must never
    unsubscribe someone who didn't click."""
    check_public_rate(request, "unsubscribe")
    await _prospect_by_token(db, token)  # 404 for unknown links
    return HTMLResponse(
        f"<html><body style='{_UNSUB_STYLE}'>"
        "<h2>Unsubscribe</h2>"
        "<p>Click below to stop receiving messages from us.</p>"
        "<form method='post'><button type='submit' "
        "style='padding:10px 24px;font-size:15px;cursor:pointer'>"
        "Unsubscribe</button></form></body></html>"
    )


# Handles both the RFC 8058 one-click POST (from the mail provider) and the
# confirmation form above. Deliberately exempt from CSRF: it is cross-origin
# by design and strictly less destructive than staying subscribed.
@router.post("/u/{token}")
async def unsubscribe_post(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
):
    check_public_rate(request, "unsubscribe")
    prospect = await _prospect_by_token(db, token)
    await _apply_unsubscribe(db, prospect)
    return HTMLResponse(
        f"<html><body style='{_UNSUB_STYLE}'><h2>You're unsubscribed</h2>"
        "<p>You won't receive further messages from us.</p></body></html>"
    )

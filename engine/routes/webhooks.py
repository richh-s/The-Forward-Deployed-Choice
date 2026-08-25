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
from engine.services.booking import record_booking_event
from engine.services.credentials import get_credentials
from engine.services.smser import send_sms
from engine.services.suppression import (
    SendBlocked,
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
    """True if this event is new; False if it was already processed."""
    if not external_id:
        return True  # nothing to dedup on — process it
    db.add(WebhookEvent(provider=provider, external_id=external_id))
    try:
        await db.flush()
        return True
    except IntegrityError:
        await db.rollback()
        return False


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
        except (SendBlocked, Exception) as exc:  # noqa: BLE001
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


@router.get("/u/{token}", response_class=HTMLResponse)
async def unsubscribe_page(token: str, db: AsyncSession = Depends(get_db)):
    row = await db.execute(
        select(Prospect).where(Prospect.unsubscribe_token == token)
    )
    prospect = row.scalar_one_or_none()
    if prospect is None:
        raise HTTPException(status_code=404, detail="Unknown link")
    await suppress(db, prospect.workspace_id, "email", prospect.email, "opt_out")
    if prospect.phone:
        await suppress(db, prospect.workspace_id, "sms", prospect.phone, "opt_out")
    prospect.stage = "opted_out"
    prospect.next_followup_at = None
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;max-width:480px;margin:80px auto;"
        "text-align:center'><h2>You're unsubscribed</h2>"
        "<p>You won't receive further messages from us.</p></body></html>"
    )


# One-click unsubscribe (RFC 8058) posts to the same URL.
@router.post("/u/{token}")
async def unsubscribe_post(token: str, db: AsyncSession = Depends(get_db)):
    await unsubscribe_page(token, db)
    return {"unsubscribed": True}

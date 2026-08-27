"""Action routes behind the dashboard forms.

Every handler re-checks workspace ownership on the target object — the
workspace_id filter is the tenancy boundary; never trust an id from a form.
"""
import csv
import difflib
import html as html_mod
import io
import json
import logging
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import (
    AuthContext,
    current_admin,
    current_auth,
    destroy_all_sessions,
)
from engine.config import get_settings
from engine.db import get_db
from engine.models import (
    PROSPECT_STAGES,
    AuditLog,
    Booking,
    Campaign,
    Draft,
    Message,
    Prospect,
    User,
    utcnow,
)
from engine.queue import enqueue
from engine.security import hash_password_async, verify_password_async
from engine.services.credentials import (
    PROVIDER_FIELDS,
    CredentialValidationError,
    set_credentials,
    validate_credential_payload,
)
from engine.services.emailer import send_test_email
from engine.services.suppression import SendBlocked, suppress
from engine.validation import valid_email, valid_phone

logger = logging.getLogger(__name__)
router = APIRouter()


def _redirect(path: str, msg: str = "", *, error: bool = False) -> RedirectResponse:
    from urllib.parse import quote_plus

    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}msg={quote_plus(msg)}" if msg else path
    if msg and error:
        url += "&err=1"  # renders as a red banner, not a green success one
    return RedirectResponse(url, status_code=303)


async def _own_campaign(db: AsyncSession, auth: AuthContext, campaign_id: str) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    return campaign


async def _own_draft(db: AsyncSession, auth: AuthContext, draft_id: str) -> Draft:
    draft = await db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    return draft


async def _own_prospect(db: AsyncSession, auth: AuthContext, prospect_id: str) -> Prospect:
    prospect = await db.get(Prospect, prospect_id)
    if prospect is None or prospect.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    return prospect


# ── campaigns ─────────────────────────────────────────────────────────


@router.post("/campaigns")
async def create_campaign(
    name: str = Form(...),
    daily_cap: int = Form(50),
    require_approval: bool = Form(False),
    auto_approve_score: float = Form(0.9),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip()
    if not name:
        return _redirect("/campaigns", "Campaign name is required", error=True)
    campaign = Campaign(
        workspace_id=auth.workspace.id,
        name=name[:200],
        daily_cap=max(1, min(daily_cap, 500)),
        require_approval=require_approval,
        auto_approve_score=min(max(auto_approve_score, 0.0), 1.0),
    )
    db.add(campaign)
    await db.flush()
    return _redirect(f"/campaigns/{campaign.id}", "Campaign created")


@router.post("/campaigns/{campaign_id}/status")
async def set_campaign_status(
    campaign_id: str,
    status: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if status not in ("draft", "active", "paused", "completed"):
        raise HTTPException(status_code=422, detail="Invalid status")
    campaign = await _own_campaign(db, auth, campaign_id)
    campaign.status = status
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="campaign_status", detail={"campaign": campaign.id, "status": status},
    ))
    return _redirect(f"/campaigns/{campaign.id}", f"Campaign {status}")


@router.post("/campaigns/{campaign_id}/settings")
async def update_campaign_settings(
    campaign_id: str,
    daily_cap: int = Form(50),
    require_approval: bool = Form(False),
    auto_approve_score: float = Form(0.9),
    send_window_start_hour: int = Form(8),
    send_window_end_hour: int = Form(18),
    timezone: str = Form("UTC"),
    sequence_json: str = Form("[]"),
    angle: str = Form(""),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    campaign = await _own_campaign(db, auth, campaign_id)
    # Validate EVERYTHING before the first mutation — get_db commits on any
    # normal return, so an error redirect after a partial write would
    # silently persist the earlier fields.
    try:
        sequence = json.loads(sequence_json or "[]")
        assert isinstance(sequence, list)
        for step in sequence:
            assert isinstance(step, dict) and float(step.get("day_offset", 0)) > 0
    except (ValueError, AssertionError, RecursionError):
        return _redirect(
            f"/campaigns/{campaign.id}",
            "Sequence must be a JSON list of {day_offset, angle} steps",
            error=True,
        )
    tz = timezone.strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except (KeyError, ValueError):
        return _redirect(
            f"/campaigns/{campaign.id}",
            f"Unknown timezone {tz!r} — use an IANA name like Europe/Berlin",
            error=True,
        )
    start = min(max(send_window_start_hour, 0), 23)
    end = min(max(send_window_end_hour, 1), 24)
    if start == end:
        return _redirect(
            f"/campaigns/{campaign.id}",
            "Send window start and end hours must differ "
            "(start > end means an overnight window)",
            error=True,
        )
    campaign.daily_cap = max(1, min(daily_cap, 500))
    campaign.require_approval = require_approval
    campaign.auto_approve_score = min(max(auto_approve_score, 0.0), 1.0)
    campaign.send_window_start_hour = start
    campaign.send_window_end_hour = end
    campaign.timezone = tz
    campaign.sequence = sequence
    playbook = dict(campaign.playbook or {})
    playbook["angle"] = angle.strip()
    campaign.playbook = playbook
    return _redirect(f"/campaigns/{campaign.id}", "Campaign updated")


@router.post("/campaigns/{campaign_id}/upload")
async def upload_prospects(
    campaign_id: str,
    file: UploadFile,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """CSV columns: email (required), name, company, title, phone,
    signals (JSON object, optional). Deduped per workspace by email."""
    campaign = await _own_campaign(db, auth, campaign_id)
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        return _redirect(f"/campaigns/{campaign.id}", "CSV too large (max 5 MB)", error=True)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _redirect(f"/campaigns/{campaign.id}", "CSV must be UTF-8", error=True)

    # Parse defensively: ragged rows land under a None key as a *list*, NUL
    # bytes and >128KB fields raise csv.Error — none of those may 500 an
    # operator upload; report the row number instead.
    rows: list[dict] = []
    line_no = 1
    try:
        # line_no is read in the except handler below, not in the loop body.
        for line_no, raw_row in enumerate(  # noqa: B007
            csv.DictReader(io.StringIO(text)), 2
        ):
            raw_row.pop(None, None)  # extra unnamed columns
            rows.append({
                (k or "").strip().lower(): (v if isinstance(v, str) else "").strip()
                for k, v in raw_row.items()
            })
    except csv.Error as exc:
        return _redirect(
            f"/campaigns/{campaign.id}",
            f"CSV could not be parsed near line {line_no}: {exc}",
            error=True,
        )
    added = skipped = invalid = 0
    # Dedup against only the emails present in this CSV (chunked IN
    # queries) — never by loading the whole workspace's email set into
    # memory, which grows without bound.
    candidates = {e for r in rows if (e := valid_email(r.get("email", "")))}
    existing: set[str] = set()
    candidate_list = sorted(candidates)
    for i in range(0, len(candidate_list), 500):
        chunk = candidate_list[i:i + 500]
        existing.update(
            e for (e,) in (await db.execute(
                select(Prospect.email).where(
                    Prospect.workspace_id == auth.workspace.id,
                    Prospect.email.in_(chunk),
                )
            )).all()
        )
    for row in rows:
        email = valid_email(row.get("email", ""))
        if not email:
            invalid += 1
            continue
        if email in existing:
            skipped += 1
            continue
        signals = {}
        # Cap per-prospect signals (they are interpolated into LLM prompts);
        # RecursionError: deeply nested JSON escapes `except ValueError`.
        if row.get("signals") and len(row["signals"]) <= 100_000:
            try:
                parsed = json.loads(row["signals"])
                if isinstance(parsed, dict):
                    signals = parsed
            except (ValueError, RecursionError):
                pass
        db.add(Prospect(
            workspace_id=auth.workspace.id,
            campaign_id=campaign.id,
            email=email,
            phone=valid_phone(row.get("phone", "")),
            name=row.get("name", "")[:200],
            company=row.get("company", "")[:200],
            title=row.get("title", "")[:200],
            signals=signals,
            stage="enriched" if signals else "new",
        ))
        existing.add(email)
        added += 1
    await db.flush()
    return _redirect(
        f"/campaigns/{campaign.id}",
        f"Imported {added} prospects ({skipped} duplicates, {invalid} invalid rows)",
    )


# ── approvals ─────────────────────────────────────────────────────────


async def _approve_draft(db: AsyncSession, auth: AuthContext, draft: Draft) -> None:
    draft.status = "approved"
    draft.reviewed_by = auth.user.id
    draft.reviewed_at = utcnow()
    await enqueue(
        db,
        "send_draft",
        {"draft_id": draft.id},
        workspace_id=auth.workspace.id,
        idempotency_key=f"send_draft:{draft.id}",
    )


@router.post("/approvals/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    subject: str = Form(""),
    body: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    draft = await _own_draft(db, auth, draft_id)
    if draft.status != "pending_review":
        return _redirect("/approvals", "Draft was already handled")
    if not body.strip():
        return _redirect("/approvals", "Body cannot be empty", error=True)
    # SMS/WhatsApp reply drafts have no subject; everything else needs one.
    if draft.channel not in ("sms", "whatsapp") and not subject.strip():
        return _redirect("/approvals", "Subject cannot be empty", error=True)
    # Learning loop: record how much the human changed before approving
    # (0 = sent verbatim, 1 = fully rewritten).
    original = f"{draft.subject}\n{draft.body}"
    edited = f"{subject.strip()[:500]}\n{body.strip()}"
    draft.edit_ratio = round(
        1.0 - difflib.SequenceMatcher(None, original, edited).ratio(), 4
    )
    draft.subject = subject.strip()[:500]
    draft.body = body.strip()
    await _approve_draft(db, auth, draft)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="draft_approved", detail={"draft_id": draft.id},
    ))
    return _redirect("/approvals", "Approved and queued for send")


@router.post("/approvals/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    reason: str = Form(""),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    draft = await _own_draft(db, auth, draft_id)
    if draft.status != "pending_review":
        return _redirect("/approvals", "Draft was already handled")
    draft.status = "rejected"
    draft.reviewed_by = auth.user.id
    draft.reviewed_at = utcnow()
    draft.reject_reason = reason.strip()[:400]
    # Rejecting an outreach draft must not strand the prospect: the original
    # compose:{prospect}:t{n} idempotency key blocks the scheduler from ever
    # composing again, so queue a fresh attempt (keyed per rejected draft)
    # carrying the reviewer's feedback. It lands back in Approvals — a
    # human still gates every send, so this cannot loop unattended.
    if draft.kind == "outreach":
        await enqueue(
            db,
            "compose_draft",
            {
                "workspace_id": auth.workspace.id,
                "prospect_id": draft.prospect_id,
                "campaign_id": draft.campaign_id,
                "touch_number": draft.touch_number,
                "rejection_feedback": draft.reject_reason or
                "The previous draft was rejected by a human reviewer.",
            },
            workspace_id=auth.workspace.id,
            idempotency_key=f"recompose:{draft.id}",
        )
        return _redirect(
            "/approvals",
            "Draft rejected — a fresh draft with your feedback will appear "
            "here shortly",
        )
    return _redirect("/approvals", "Draft rejected")


@router.post("/approvals/bulk-approve")
async def bulk_approve(
    min_score: float = Form(0.9),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    # Clamp like auto_approve_score: a typo'd threshold (e.g. -1) must not
    # approve judge-rejected drafts wholesale.
    min_score = min(max(min_score, 0.0), 1.0)
    # judge_score is NULL on reply drafts, so the comparison excludes them —
    # replies always get individual human review.
    rows = await db.execute(
        select(Draft).where(
            Draft.workspace_id == auth.workspace.id,
            Draft.status == "pending_review",
            Draft.judge_score >= min_score,
        )
    )
    count = 0
    for draft in rows.scalars().all():
        await _approve_draft(db, auth, draft)
        count += 1
    if count:
        db.add(AuditLog(
            workspace_id=auth.workspace.id, user_id=auth.user.id,
            action="bulk_approve", detail={"count": count, "min_score": min_score},
        ))
    return _redirect("/approvals", f"Approved {count} drafts scoring ≥ {min_score}")


@router.post("/approvals/{draft_id}/test-send")
async def test_send_draft(
    draft_id: str,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Email the draft to the reviewer's own address — a real end-to-end
    check of credentials and rendering without touching any prospect."""
    draft = await _own_draft(db, auth, draft_id)
    try:
        await send_test_email(
            db, auth.workspace,
            to_email=auth.user.email,
            subject=draft.subject or "(no subject — SMS draft)",
            body=draft.body,
        )
    except SendBlocked as exc:
        return _redirect("/approvals", f"Test send blocked: {exc.reason}", error=True)
    return _redirect("/approvals", f"Test sent to {auth.user.email}")


# ── prospects ─────────────────────────────────────────────────────────


@router.post("/prospects/{prospect_id}/stage")
async def set_prospect_stage(
    prospect_id: str,
    stage: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if stage not in PROSPECT_STAGES:
        raise HTTPException(status_code=422, detail="Invalid stage")
    prospect = await _own_prospect(db, auth, prospect_id)
    prospect.stage = stage
    if stage == "opted_out":
        await suppress(db, auth.workspace.id, "email", prospect.email, "manual")
        if prospect.phone:
            await suppress(db, auth.workspace.id, "sms", prospect.phone, "manual")
            await suppress(
                db, auth.workspace.id, "whatsapp", prospect.phone, "manual"
            )
        prospect.next_followup_at = None
    return _redirect(f"/prospects/{prospect.id}", f"Stage set to {stage}")


@router.post("/prospects/{prospect_id}/delete")
async def delete_prospect(
    prospect_id: str,
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Erase a prospect's personal data (GDPR/CCPA deletion).

    Removes the prospect row and their message/draft/booking content.
    The suppression entry is intentionally KEPT — retaining the address on
    the do-not-contact list is the lawful basis for honoring the opt-out."""
    prospect = await _own_prospect(db, auth, prospect_id)
    email = prospect.email
    # Keep them un-contactable even after erasure.
    await suppress(db, auth.workspace.id, "email", email, "manual")
    if prospect.phone:
        await suppress(db, auth.workspace.id, "sms", prospect.phone, "manual")
        await suppress(db, auth.workspace.id, "whatsapp", prospect.phone, "manual")
    for model in (Message, Draft, Booking):
        await db.execute(sa_delete(model).where(
            model.workspace_id == auth.workspace.id,
            model.prospect_id == prospect.id,
        ))
    # Pending jobs still reference the erased prospect (some payloads embed
    # inbound message text — PII) — remove them rather than letting each
    # dead-letter with error noise.
    from engine.models import Job

    jobs = (await db.execute(
        select(Job).where(
            Job.workspace_id == auth.workspace.id,
            Job.status.in_(["pending", "failed"]),
        )
    )).scalars().all()
    for job in jobs:
        if (job.payload or {}).get("prospect_id") == prospect.id:
            await db.delete(job)
    await db.delete(prospect)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="prospect_deleted", detail={"prospect_id": prospect_id},
    ))
    return _redirect("/prospects", "Prospect data erased")


@router.post("/prospects/{prospect_id}/compose")
async def compose_now(
    prospect_id: str,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Compose a draft for this prospect on demand — preview the pipeline
    (composer + judge + approval queue) without waiting for the scheduler.
    The draft lands in Approvals; nothing sends without the normal gates."""
    prospect = await _own_prospect(db, auth, prospect_id)
    if prospect.stage == "opted_out":
        return _redirect(f"/prospects/{prospect.id}", "Prospect has opted out", error=True)
    job = await enqueue(
        db,
        "compose_draft",
        {
            "workspace_id": auth.workspace.id,
            "prospect_id": prospect.id,
            "campaign_id": prospect.campaign_id,
            "touch_number": prospect.touch_count + 1,
            "manual": True,
        },
        workspace_id=auth.workspace.id,
        # Dedupe double-clicks without blocking a deliberate re-compose later.
        idempotency_key=f"compose:manual:{prospect.id}"
        f":{utcnow().strftime('%Y%m%d%H%M')}",
    )
    if job is None:
        return _redirect(
            f"/prospects/{prospect.id}", "A compose was already queued just now"
        )
    return _redirect(
        f"/prospects/{prospect.id}",
        "Draft queued — it will appear in Approvals once composed and judged",
    )


@router.post("/prospects/{prospect_id}/signals")
async def set_prospect_signals(
    prospect_id: str,
    signals_json: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    prospect = await _own_prospect(db, auth, prospect_id)
    if len(signals_json) > 100_000:
        return _redirect(
            f"/prospects/{prospect.id}",
            "Signals too large (max 100 KB) — they are sent to the model "
            "verbatim on every compose",
            error=True,
        )
    try:
        signals = json.loads(signals_json)
        assert isinstance(signals, dict)
    except (ValueError, AssertionError, RecursionError):
        return _redirect(f"/prospects/{prospect.id}", "Signals must be a JSON object", error=True)
    prospect.signals = signals
    if prospect.stage == "new" and signals:
        prospect.stage = "enriched"
    return _redirect(f"/prospects/{prospect.id}", "Signals updated")


# ── jobs (queue operations) ──────────────────────────────────────────


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    from engine.models import Job

    job = await db.get(Job, job_id)
    if job is None or job.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    if job.status not in ("failed", "dead"):
        return _redirect("/jobs", "Only failed or dead jobs can be retried")
    if job.status == "dead":
        job.attempts = 0  # dead jobs get a fresh budget after a manual fix
    job.status = "failed"
    job.run_after = utcnow()
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="job_retried", detail={"job_id": job.id, "type": job.type},
    ))
    return _redirect("/jobs", "Job requeued")


# ── settings (admin) ─────────────────────────────────────────────────


@router.post("/settings/workspace")
async def update_workspace(
    name: str = Form(...),
    from_email: str = Form(""),
    from_name: str = Form(""),
    sms_sender_id: str = Form(""),
    calcom_event_url: str = Form(""),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = auth.workspace
    # Validate everything before the first mutation (get_db commits on any
    # normal return — an error redirect must not persist partial edits).
    if from_email and not valid_email(from_email):
        return _redirect("/settings", "Invalid sending address", error=True)
    url = calcom_event_url.strip()
    if url and not url.startswith("https://"):
        return _redirect("/settings", "Booking URL must be https", error=True)
    new_from_email = valid_email(from_email) if from_email else None
    if new_from_email != ws.from_email:
        # The warm-up ramp restarts from this moment for a changed sending
        # identity (see deliverability.py) — record when it happened.
        db.add(AuditLog(
            workspace_id=ws.id, user_id=auth.user.id,
            action="workspace_updated",
            detail={"from_email_changed": True},
        ))
    ws.name = name.strip()[:200] or ws.name
    ws.from_email = new_from_email
    ws.from_name = from_name.strip()[:200] or None
    ws.sms_sender_id = sms_sender_id.strip()[:20] or None
    ws.calcom_event_url = url or None
    db.add(ws)
    return _redirect("/settings", "Workspace updated")


@router.post("/settings/playbook")
async def update_playbook(
    company_name: str = Form(""),
    company_description: str = Form(""),
    value_proposition: str = Form(""),
    icp_definition: str = Form(""),
    style_guide: str = Form(""),
    capacity_notes: str = Form(""),
    pricing_notes: str = Form(""),
    case_studies: str = Form(""),
    examples: str = Form(""),
    positioning: str = Form(""),
    objection_handling: str = Form(""),
    sign_off: str = Form(""),
    support_contact: str = Form(""),
    honesty_constraints: str = Form(""),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    constraints = [c.strip() for c in honesty_constraints.splitlines() if c.strip()]
    playbook = {
        "company_name": company_name.strip(),
        "company_description": company_description.strip(),
        "value_proposition": value_proposition.strip(),
        "icp_definition": icp_definition.strip(),
        "style_guide": style_guide.strip(),
        "capacity_notes": capacity_notes.strip(),
        "pricing_notes": pricing_notes.strip(),
        "case_studies": case_studies.strip(),
        "examples": examples.strip(),
        "positioning": positioning.strip(),
        "objection_handling": objection_handling.strip(),
        "sign_off": sign_off.strip(),
        "support_contact": support_contact.strip(),
    }
    if constraints:
        playbook["honesty_constraints"] = constraints
    # Preserve keys the form doesn't manage (e.g. seed-provided benchmarks,
    # future non-string entries) — saving the form must never wipe them.
    preserved = {
        k: v for k, v in (auth.workspace.playbook or {}).items()
        if k not in playbook and k != "honesty_constraints"
    }
    auth.workspace.playbook = {
        **preserved, **{k: v for k, v in playbook.items() if v}
    }
    db.add(auth.workspace)
    return _redirect("/settings", "Playbook saved")


@router.post("/settings/models")
async def update_models(
    compose_model: str = Form(""),
    reply_model: str = Form(""),
    judge_model: str = Form(""),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Per-workspace model overrides by role. Blank = platform default.
    A 'local:' prefix routes the role to the self-hosted LOCAL_LLM_BASE_URL."""
    cfg = {
        "compose": compose_model.strip(),
        "reply": reply_model.strip(),
        "judge": judge_model.strip(),
    }
    auth.workspace.llm_config = {k: v for k, v in cfg.items() if v}
    db.add(auth.workspace)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="models_updated", detail=auth.workspace.llm_config,
    ))
    return _redirect("/settings", "Model configuration saved")


@router.post("/settings/credentials/{provider}")
async def update_credentials(
    provider: str,
    payload_json: str = Form(...),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    if provider not in PROVIDER_FIELDS:
        raise HTTPException(status_code=404)
    try:
        payload = json.loads(payload_json)
        assert isinstance(payload, dict)
    except (ValueError, AssertionError, RecursionError):
        return _redirect("/settings", "Credentials must be a JSON object", error=True)
    try:
        payload = validate_credential_payload(provider, payload)
    except CredentialValidationError as exc:
        return _redirect("/settings", str(exc), error=True)
    # MERGE with what's stored: re-saving just the api_key must not wipe the
    # webhook_secret (which would silently reject all future webhooks), and
    # must not regenerate the Africa's Talking URL token (which would
    # invalidate the URL already registered in their dashboard).
    from engine.services.credentials import get_credentials as _get_creds

    existing = await _get_creds(db, auth.workspace.id, provider) or {}
    payload = {**existing, **payload}
    # Auto-generate the webhook URL token for Africa's Talking.
    if provider == "africastalking" and "webhook_token" not in payload:
        payload["webhook_token"] = secrets.token_urlsafe(24)
    await set_credentials(db, auth.workspace.id, provider, payload)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="credentials_updated", detail={"provider": provider},
    ))
    return _redirect("/settings", f"{provider} credentials saved")


@router.get("/settings/export-judge-data")
async def export_judge_data(
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Human-reviewed drafts as JSONL fine-tuning rows for a workspace
    judge: model input (signals + draft) with both the API judge's verdict
    and the human's decision as the label. Feeds the Week-11 LoRA critic
    seam in engine/services/judge.py."""
    from fastapi.responses import PlainTextResponse

    from engine.services import learning

    rows = await learning.export_judge_training_rows(db, auth.workspace.id)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="judge_data_exported", detail={"rows": len(rows)},
    ))
    return PlainTextResponse(
        body,
        media_type="application/jsonl",
        headers={
            "Content-Disposition":
                'attachment; filename="judge_training_data.jsonl"'
        },
    )


@router.post("/settings/killswitch")
async def update_killswitch(
    opt_out_rate: str = Form(""),
    bounce_rate: str = Form(""),
    cost_per_qualified_lead: str = Form(""),
    max_llm_cost_usd: str = Form(""),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Per-workspace kill-switch threshold overrides. Blank = platform
    default. Rates are fractions (0.05 = 5%)."""
    overrides: dict[str, float] = {}
    for field, value, lo, hi in (
        ("opt_out_rate", opt_out_rate, 0.0, 1.0),
        ("bounce_rate", bounce_rate, 0.0, 1.0),
        ("cost_per_qualified_lead", cost_per_qualified_lead, 0.01, 100000.0),
        ("max_llm_cost_usd", max_llm_cost_usd, 0.0, 1000000.0),
    ):
        value = value.strip()
        if not value:
            continue
        try:
            parsed = float(value)
        except ValueError:
            return _redirect(
                "/settings", f"{field} must be a number", error=True
            )
        if not (lo <= parsed <= hi):
            return _redirect(
                "/settings",
                f"{field} must be between {lo} and {hi}",
                error=True,
            )
        overrides[field] = parsed
    auth.workspace.killswitch = overrides
    db.add(auth.workspace)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="killswitch_thresholds_updated", detail=overrides,
    ))
    return _redirect(
        "/settings",
        "Kill-switch thresholds saved" if overrides
        else "Kill-switch thresholds reset to platform defaults",
    )


@router.get("/prospects.csv")
async def export_prospects(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Workspace prospects as CSV — data can leave the way it came in."""
    from fastapi.responses import PlainTextResponse

    rows = (await db.execute(
        select(Prospect)
        .where(Prospect.workspace_id == auth.workspace.id)
        .order_by(Prospect.created_at)
    )).scalars().all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "email", "name", "company", "title", "phone", "stage", "icp_segment",
        "touch_count", "avg_confidence", "signals",
    ])
    for p in rows:
        writer.writerow([
            p.email, p.name, p.company, p.title, p.phone or "", p.stage,
            p.icp_segment or "", p.touch_count,
            p.avg_confidence if p.avg_confidence is not None else "",
            json.dumps(p.signals or {}, ensure_ascii=False),
        ])
    return PlainTextResponse(
        out.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="prospects.csv"'
        },
    )


@router.post("/settings/reply-approval")
async def update_reply_approval(
    require_reply_approval: bool = Form(False),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    auth.workspace.require_reply_approval = require_reply_approval
    db.add(auth.workspace)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="reply_approval_changed",
        detail={"require_reply_approval": require_reply_approval},
    ))
    state = "held for review" if require_reply_approval else "sent automatically"
    return _redirect("/settings", f"Reply-agent responses will be {state}")


@router.post("/settings/resume-outbound")
async def resume_outbound(
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    auth.workspace.outbound_paused = False
    auth.workspace.pause_reason = None
    db.add(auth.workspace)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="outbound_resumed", detail={},
    ))
    return _redirect("/settings", "Outbound resumed")


@router.post("/settings/pause-outbound")
async def pause_outbound(
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    auth.workspace.outbound_paused = True
    auth.workspace.pause_reason = f"Paused manually by {auth.user.email}"
    db.add(auth.workspace)
    return _redirect("/settings", "Outbound paused")


@router.post("/settings/users")
async def add_user(
    email: str = Form(...),
    name: str = Form(""),
    password: str = Form(...),
    role: str = Form("operator"),
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    addr = valid_email(email)
    if not addr:
        return _redirect("/settings", "Invalid email", error=True)
    if len(password) < 10:
        return _redirect("/settings", "Password must be at least 10 characters", error=True)
    if role not in ("admin", "operator"):
        role = "operator"
    exists = (await db.execute(select(User).where(User.email == addr))).first()
    if exists:
        # Generic message — don't confirm whether an address (possibly from
        # another tenant) has an account here.
        return _redirect("/settings", "Could not create that user", error=True)
    db.add(User(
        workspace_id=auth.workspace.id,
        email=addr,
        name=name.strip()[:200],
        password_hash=await hash_password_async(password),
        role=role,
        # The admin knows this temporary password; force a change on first use.
        must_change_password=True,
    ))
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="user_added", detail={"email": addr, "role": role},
    ))
    return _redirect(
        "/settings",
        f"User {addr} added — they must set their own password on first login",
    )


@router.post("/settings/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    auth: AuthContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin account recovery: issue a one-time temporary password for a
    locked-out teammate, revoking all their sessions. The temporary password
    is rendered ONCE in the response body (never in a URL, where it would
    land in access logs)."""
    target = await db.get(User, user_id)
    if target is None or target.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    if target.id == auth.user.id:
        return _redirect(
            "/settings", "Use the password change form for your own account"
        )
    temp_password = secrets.token_urlsafe(12)
    target.password_hash = await hash_password_async(temp_password)
    target.must_change_password = True
    revoked = await destroy_all_sessions(db, target.id)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="password_reset",
        detail={"target_user": target.email, "sessions_revoked": revoked},
    ))
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:80px auto'>"
        f"<h2>Temporary password for {html_mod.escape(target.email)}</h2>"
        f"<p>Share it over a trusted channel — it is shown only once:</p>"
        f"<p><code style='font-size:18px'>{html_mod.escape(temp_password)}</code></p>"
        "<p>They must set their own password at first login. All their "
        f"existing sessions ({revoked}) were signed out.</p>"
        "<p><a href='/settings'>Back to Settings</a></p></body>"
    )


@router.post("/settings/password")
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Change own password; revokes every other session for the account."""
    if not await verify_password_async(current_password, auth.user.password_hash):
        return _redirect("/settings", "Current password is incorrect", error=True)
    if len(new_password) < 10:
        return _redirect("/settings", "Password must be at least 10 characters")
    auth.user.password_hash = await hash_password_async(new_password)
    auth.user.must_change_password = False
    revoked = await destroy_all_sessions(db, auth.user.id)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="password_changed", detail={"sessions_revoked": revoked},
    ))
    # The caller's own session was revoked too — send them to log in again.
    # Also clear the (now dead) session cookie: the CSRF check binds to the
    # session cookie when one is present, so a stale cookie would 403 the
    # very next login attempt.
    settings = get_settings()
    response = RedirectResponse(
        "/login?error=Password+changed+—+log+in+again", status_code=303
    )
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )
    return response

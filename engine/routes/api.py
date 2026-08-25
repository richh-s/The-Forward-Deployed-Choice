"""Action routes behind the dashboard forms.

Every handler re-checks workspace ownership on the target object — the
workspace_id filter is the tenancy boundary; never trust an id from a form.
"""
import csv
import io
import json
import logging
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import AuthContext, current_admin, current_auth
from engine.db import get_db
from engine.models import (
    PROSPECT_STAGES,
    AuditLog,
    Campaign,
    Draft,
    Prospect,
    User,
    utcnow,
)
from engine.queue import enqueue
from engine.security import hash_password
from engine.services.credentials import PROVIDER_FIELDS, set_credentials
from engine.services.suppression import suppress
from engine.validation import valid_email, valid_phone

logger = logging.getLogger(__name__)
router = APIRouter()


def _redirect(path: str, msg: str = "") -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}msg={msg.replace(' ', '+')}" if msg else path
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
        return _redirect("/campaigns", "Campaign name is required")
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
    try:
        sequence = json.loads(sequence_json or "[]")
        assert isinstance(sequence, list)
        for step in sequence:
            assert isinstance(step, dict) and float(step.get("day_offset", 0)) > 0
    except (ValueError, AssertionError):
        return _redirect(
            f"/campaigns/{campaign.id}",
            "Sequence must be a JSON list of {day_offset, angle} steps",
        )
    campaign.daily_cap = max(1, min(daily_cap, 500))
    campaign.require_approval = require_approval
    campaign.auto_approve_score = min(max(auto_approve_score, 0.0), 1.0)
    campaign.send_window_start_hour = min(max(send_window_start_hour, 0), 23)
    campaign.send_window_end_hour = min(max(send_window_end_hour, 1), 24)
    campaign.timezone = timezone.strip() or "UTC"
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
        return _redirect(f"/campaigns/{campaign.id}", "CSV too large (max 5 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _redirect(f"/campaigns/{campaign.id}", "CSV must be UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    added = skipped = invalid = 0
    existing = {
        e for (e,) in (await db.execute(
            select(Prospect.email).where(Prospect.workspace_id == auth.workspace.id)
        )).all()
    }
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        email = valid_email(row.get("email", ""))
        if not email:
            invalid += 1
            continue
        if email in existing:
            skipped += 1
            continue
        signals = {}
        if row.get("signals"):
            try:
                parsed = json.loads(row["signals"])
                if isinstance(parsed, dict):
                    signals = parsed
            except ValueError:
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
    subject: str = Form(...),
    body: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    draft = await _own_draft(db, auth, draft_id)
    if draft.status != "pending_review":
        return _redirect("/approvals", "Draft was already handled")
    if not subject.strip() or not body.strip():
        return _redirect("/approvals", "Subject and body cannot be empty")
    draft.subject = subject.strip()[:500]
    draft.body = body.strip()
    await _approve_draft(db, auth, draft)
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
    return _redirect("/approvals", "Draft rejected")


@router.post("/approvals/bulk-approve")
async def bulk_approve(
    min_score: float = Form(0.9),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
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
    return _redirect("/approvals", f"Approved {count} drafts scoring ≥ {min_score}")


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
        prospect.next_followup_at = None
    return _redirect(f"/prospects/{prospect.id}", f"Stage set to {stage}")


@router.post("/prospects/{prospect_id}/signals")
async def set_prospect_signals(
    prospect_id: str,
    signals_json: str = Form(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    prospect = await _own_prospect(db, auth, prospect_id)
    try:
        signals = json.loads(signals_json)
        assert isinstance(signals, dict)
    except (ValueError, AssertionError):
        return _redirect(f"/prospects/{prospect.id}", "Signals must be a JSON object")
    prospect.signals = signals
    if prospect.stage == "new" and signals:
        prospect.stage = "enriched"
    return _redirect(f"/prospects/{prospect.id}", "Signals updated")


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
    ws.name = name.strip()[:200] or ws.name
    if from_email and not valid_email(from_email):
        return _redirect("/settings", "Invalid sending address")
    ws.from_email = valid_email(from_email) if from_email else None
    ws.from_name = from_name.strip()[:200] or None
    ws.sms_sender_id = sms_sender_id.strip()[:20] or None
    url = calcom_event_url.strip()
    if url and not url.startswith("https://"):
        return _redirect("/settings", "Booking URL must be https")
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
        "sign_off": sign_off.strip(),
        "support_contact": support_contact.strip(),
    }
    if constraints:
        playbook["honesty_constraints"] = constraints
    auth.workspace.playbook = {k: v for k, v in playbook.items() if v}
    db.add(auth.workspace)
    return _redirect("/settings", "Playbook saved")


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
    except (ValueError, AssertionError):
        return _redirect("/settings", "Credentials must be a JSON object")
    payload = {k: str(v) for k, v in payload.items() if v}
    # Auto-generate the webhook URL token for Africa's Talking.
    if provider == "africastalking" and "webhook_token" not in payload:
        payload["webhook_token"] = secrets.token_urlsafe(24)
    await set_credentials(db, auth.workspace.id, provider, payload)
    db.add(AuditLog(
        workspace_id=auth.workspace.id, user_id=auth.user.id,
        action="credentials_updated", detail={"provider": provider},
    ))
    return _redirect("/settings", f"{provider} credentials saved")


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
        return _redirect("/settings", "Invalid email")
    if len(password) < 10:
        return _redirect("/settings", "Password must be at least 10 characters")
    if role not in ("admin", "operator"):
        role = "operator"
    exists = (await db.execute(select(User).where(User.email == addr))).first()
    if exists:
        return _redirect("/settings", "A user with that email already exists")
    db.add(User(
        workspace_id=auth.workspace.id,
        email=addr,
        name=name.strip()[:200],
        password_hash=hash_password(password),
        role=role,
    ))
    return _redirect("/settings", f"User {addr} added")

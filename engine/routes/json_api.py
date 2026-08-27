"""Read-only JSON API (/api/v1) for the Next.js dashboard.

Reads live here; writes go through the existing form routes (api.py), which
the SPA calls with FormData + the csrf_token from /api/v1/me — one set of
validation and audit logic, two frontends. Same-origin only: the SPA is
statically exported and mounted at /app by the same FastAPI process, so the
session cookie and CSRF model are identical to the server-rendered pages.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import AuthContext, current_auth
from engine.config import get_settings
from engine.csrf import new_prelogin_token, set_prelogin_cookie
from engine.db import get_db
from engine.models import (
    PROSPECT_STAGES,
    AuditLog,
    Booking,
    Campaign,
    Draft,
    Job,
    Message,
    Prospect,
    User,
)
from engine.routes.dashboard import (
    APPROVALS_PAGE_SIZE,
    CAMPAIGN_PROSPECTS_PAGE_SIZE,
    JOBS_PAGE_SIZE,
    PROSPECTS_PAGE_SIZE,
    _paged,
)
from engine.security import csrf_token_for
from engine.services.credentials import PROVIDER_FIELDS, configured_providers
from engine.services.killswitch import compute_metrics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _prospect_row(p: Prospect) -> dict:
    return {
        "id": p.id,
        "email": p.email,
        "name": p.name,
        "company": p.company,
        "title": p.title,
        "phone": p.phone,
        "stage": p.stage,
        "icp_segment": p.icp_segment,
        "touch_count": p.touch_count,
        "avg_confidence": p.avg_confidence,
        "campaign_id": p.campaign_id,
        "signals": p.signals or {},
        "next_followup_at": _iso(p.next_followup_at),
        "hubspot_contact_id": p.hubspot_contact_id,
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
    }


def _campaign_row(c: Campaign) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "status": c.status,
        "daily_cap": c.daily_cap,
        "require_approval": c.require_approval,
        "auto_approve_score": c.auto_approve_score,
        "send_window_start_hour": c.send_window_start_hour,
        "send_window_end_hour": c.send_window_end_hour,
        "timezone": c.timezone,
        "sequence": c.sequence or [],
        "angle": (c.playbook or {}).get("angle", ""),
        "created_at": _iso(c.created_at),
    }


def _draft_row(d: Draft) -> dict:
    return {
        "id": d.id,
        "prospect_id": d.prospect_id,
        "campaign_id": d.campaign_id,
        "kind": d.kind,
        "channel": d.channel,
        "subject": d.subject,
        "body": d.body,
        "mode": d.mode,
        "angle": d.angle,
        "avg_confidence": d.avg_confidence,
        "judge_score": d.judge_score,
        "judge_scores": d.judge_scores or {},
        "judge_feedback": d.judge_feedback,
        "grounding_notes": d.grounding_notes,
        "touch_number": d.touch_number,
        "status": d.status,
        "auto_approved": d.auto_approved,
        "reject_reason": d.reject_reason,
        "compose_cost_usd": d.compose_cost_usd,
        "created_at": _iso(d.created_at),
    }


async def _common(db: AsyncSession, auth: AuthContext) -> dict:
    dead_jobs = int((await db.execute(
        select(func.count()).select_from(Job).where(
            Job.workspace_id == auth.workspace.id, Job.status == "dead"
        )
    )).scalar_one())
    return {"dead_jobs": dead_jobs, "live_mode": get_settings().live_mode}


@router.get("/prelogin")
async def prelogin() -> JSONResponse:
    """Mint the double-submit CSRF token for the SPA's login form (the
    cookie is httponly, so the token is returned in the body too — same
    value the server-rendered login page embeds in its HTML)."""
    token = new_prelogin_token()
    response = JSONResponse({"csrf_token": token})
    set_prelogin_cookie(response, token)
    return response


@router.get("/me")
async def me(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    session_token = request.cookies.get(get_settings().session_cookie_name, "")
    ws = auth.workspace
    return {
        "user": {
            "id": auth.user.id,
            "email": auth.user.email,
            "name": auth.user.name,
            "role": auth.user.role,
        },
        "workspace": {
            "id": ws.id,
            "name": ws.name,
            "slug": ws.slug,
            "outbound_paused": ws.outbound_paused,
            "pause_reason": ws.pause_reason,
            "require_reply_approval": ws.require_reply_approval,
            "from_email": ws.from_email,
            "from_name": ws.from_name,
            "sms_sender_id": ws.sms_sender_id,
            "calcom_event_url": ws.calcom_event_url,
            "playbook": ws.playbook or {},
            "llm_config": ws.llm_config or {},
            "killswitch": ws.killswitch or {},
        },
        # For FormData writes against the existing form routes.
        "csrf_token": csrf_token_for(session_token),
        "stages": PROSPECT_STAGES,
        **(await _common(db, auth)),
    }


@router.get("/summary")
async def summary(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    ws_id = auth.workspace.id
    stage_rows = await db.execute(
        select(Prospect.stage, func.count())
        .where(Prospect.workspace_id == ws_id)
        .group_by(Prospect.stage)
    )
    pending_drafts = int((await db.execute(
        select(func.count()).select_from(Draft).where(
            Draft.workspace_id == ws_id, Draft.status == "pending_review"
        )
    )).scalar_one())
    upcoming = (await db.execute(
        select(Booking)
        .where(
            Booking.workspace_id == ws_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
        )
        .order_by(Booking.start_time)
        .limit(5)
    )).scalars().all()
    escalations = (await db.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == ws_id, AuditLog.action == "escalation")
        .order_by(AuditLog.created_at.desc())
        .limit(5)
    )).scalars().all()
    metrics = await compute_metrics(db, auth.workspace)
    return {
        "stages": PROSPECT_STAGES,
        "stage_counts": dict(stage_rows.all()),
        "pending_drafts": pending_drafts,
        "metrics": metrics,
        "upcoming": [
            {
                "id": b.id,
                "prospect_id": b.prospect_id,
                "start_time": _iso(b.start_time),
                "status": b.status,
            }
            for b in upcoming
        ],
        "escalations": [
            {
                "created_at": _iso(e.created_at),
                "reason": (e.detail or {}).get("reason") or "",
                "prospect_id": (e.detail or {}).get("prospect_id"),
            }
            for e in escalations
        ],
        **(await _common(db, auth)),
    }


@router.get("/campaigns")
async def campaigns(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Campaign)
        .where(Campaign.workspace_id == auth.workspace.id)
        .order_by(Campaign.created_at.desc())
    )).scalars().all()
    count_rows = await db.execute(
        select(Prospect.campaign_id, func.count())
        .where(Prospect.workspace_id == auth.workspace.id)
        .group_by(Prospect.campaign_id)
    )
    counts = {cid: int(n) for cid, n in count_rows.all() if cid}
    cost_rows = await db.execute(
        select(Draft.campaign_id, func.coalesce(func.sum(Draft.compose_cost_usd), 0.0))
        .where(Draft.workspace_id == auth.workspace.id)
        .group_by(Draft.campaign_id)
    )
    costs = {cid: round(float(v), 4) for cid, v in cost_rows.all() if cid}
    return {
        "campaigns": [
            {
                **_campaign_row(c),
                "prospect_count": counts.get(c.id, 0),
                "llm_cost_usd": costs.get(c.id, 0.0),
            }
            for c in rows
        ],
    }


@router.get("/campaigns/{campaign_id}")
async def campaign_detail(
    campaign_id: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    stage_rows = await db.execute(
        select(Prospect.stage, func.count())
        .where(Prospect.campaign_id == campaign.id)
        .group_by(Prospect.stage)
    )
    result, pager = await _paged(
        db, request,
        select(Prospect)
        .where(Prospect.campaign_id == campaign.id)
        .order_by(Prospect.created_at.desc()),
        CAMPAIGN_PROSPECTS_PAGE_SIZE,
    )
    return {
        "campaign": _campaign_row(campaign),
        "stages": PROSPECT_STAGES,
        "stage_counts": dict(stage_rows.all()),
        "prospects": [_prospect_row(p) for p in result.scalars().all()],
        "pager": pager,
    }


@router.get("/prospects")
async def prospects(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    stage = request.query_params.get("stage", "")
    q = request.query_params.get("q", "").strip()[:200]
    query = select(Prospect).where(Prospect.workspace_id == auth.workspace.id)
    if stage and stage in PROSPECT_STAGES:
        query = query.where(Prospect.stage == stage)
    if q:
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        query = query.where(
            Prospect.email.ilike(pattern, escape="\\")
            | Prospect.name.ilike(pattern, escape="\\")
            | Prospect.company.ilike(pattern, escape="\\")
        )
    result, pager = await _paged(
        db, request, query.order_by(Prospect.updated_at.desc()),
        PROSPECTS_PAGE_SIZE,
    )
    return {
        "prospects": [_prospect_row(p) for p in result.scalars().all()],
        "pager": pager,
        "stages": PROSPECT_STAGES,
    }


@router.get("/prospects/{prospect_id}")
async def prospect_detail(
    prospect_id: str,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    prospect = await db.get(Prospect, prospect_id)
    if prospect is None or prospect.workspace_id != auth.workspace.id:
        raise HTTPException(status_code=404)
    timeline = (await db.execute(
        select(Message)
        .where(Message.prospect_id == prospect.id)
        .order_by(Message.created_at)
    )).scalars().all()
    drafts = (await db.execute(
        select(Draft)
        .where(Draft.prospect_id == prospect.id)
        .order_by(Draft.created_at.desc())
    )).scalars().all()
    bookings = (await db.execute(
        select(Booking)
        .where(Booking.prospect_id == prospect.id)
        .order_by(Booking.created_at.desc())
    )).scalars().all()
    return {
        "prospect": _prospect_row(prospect),
        "stages": PROSPECT_STAGES,
        "timeline": [
            {
                "id": m.id,
                "channel": m.channel,
                "direction": m.direction,
                "subject": m.subject,
                "body": m.body,
                "status": m.status,
                "intent": m.intent,
                "created_at": _iso(m.created_at),
            }
            for m in timeline
        ],
        "drafts": [_draft_row(d) for d in drafts],
        "bookings": [
            {
                "id": b.id,
                "start_time": _iso(b.start_time),
                "status": b.status,
            }
            for b in bookings
        ],
    }


@router.get("/approvals")
async def approvals(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    result, pager = await _paged(
        db, request,
        select(Draft, Prospect)
        .join(Prospect, Draft.prospect_id == Prospect.id)
        .where(
            Draft.workspace_id == auth.workspace.id,
            Draft.status == "pending_review",
        )
        .order_by(Draft.created_at),
        APPROVALS_PAGE_SIZE,
    )
    return {
        "rows": [
            {"draft": _draft_row(d), "prospect": _prospect_row(p)}
            for d, p in result.all()
        ],
        "pager": pager,
    }


@router.get("/jobs")
async def jobs(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    ws_id = auth.workspace.id
    status_rows = await db.execute(
        select(Job.status, func.count())
        .where(Job.workspace_id == ws_id)
        .group_by(Job.status)
    )
    result, pager = await _paged(
        db, request,
        select(Job)
        .where(Job.workspace_id == ws_id, Job.status.in_(["failed", "dead"]))
        .order_by(Job.updated_at.desc()),
        JOBS_PAGE_SIZE,
    )
    return {
        "status_counts": dict(status_rows.all()),
        "problem_jobs": [
            {
                "id": j.id,
                "type": j.type,
                "status": j.status,
                "attempts": j.attempts,
                "max_attempts": j.max_attempts,
                "last_error": (j.last_error or "")[:1000],
                "updated_at": _iso(j.updated_at),
            }
            for j in result.scalars().all()
        ],
        "pager": pager,
    }


@router.get("/analytics")
async def analytics(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    from engine.services import deliverability, learning

    ws_id = auth.workspace.id
    metrics = await compute_metrics(db, auth.workspace)

    async def _msg_count(*conds) -> int:
        return int((await db.execute(
            select(func.count()).select_from(Message).where(
                Message.workspace_id == ws_id, *conds
            )
        )).scalar_one())

    sent = await _msg_count(Message.channel == "email", Message.direction == "out")
    opened = await _msg_count(
        Message.channel == "email", Message.status.in_(["opened", "clicked"])
    )
    replied = int((await db.execute(
        select(func.count(func.distinct(Message.prospect_id))).where(
            Message.workspace_id == ws_id, Message.direction == "in"
        )
    )).scalar_one())
    warm = int((await db.execute(
        select(func.count()).select_from(Prospect).where(
            Prospect.workspace_id == ws_id,
            Prospect.stage.in_(["warm", "booked"]),
        )
    )).scalar_one())
    booked = int((await db.execute(
        select(func.count()).select_from(Booking).where(
            Booking.workspace_id == ws_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
        )
    )).scalar_one())
    return {
        "metrics": metrics,
        "funnel": [
            {"label": "Emails sent", "value": sent},
            {"label": "Opened", "value": opened},
            {"label": "Replied (prospects)", "value": replied},
            {"label": "Warm / qualified", "value": warm},
            {"label": "Meetings booked", "value": booked},
        ],
        "angles": await learning.angle_performance(db, ws_id),
        "calibration": await learning.judge_calibration(db, ws_id),
        "edits": await learning.edit_stats(db, ws_id),
        "delivery": await deliverability.summary(db, auth.workspace),
    }


@router.get("/settings")
async def settings_data(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    from engine.services.credentials import get_credentials

    settings = get_settings()
    base_url = settings.base_url
    slug = auth.workspace.slug
    at_url = f"{base_url}/webhooks/{slug}/sms/<webhook_token>"
    if auth.user.role == "admin":
        at_creds = await get_credentials(db, auth.workspace.id, "africastalking")
        if at_creds and at_creds.get("webhook_token"):
            at_url = f"{base_url}/webhooks/{slug}/sms/{at_creds['webhook_token']}"
    team = (await db.execute(
        select(User)
        .where(User.workspace_id == auth.workspace.id)
        .order_by(User.created_at)
    )).scalars().all()
    return {
        "provider_fields": PROVIDER_FIELDS,
        "configured": await configured_providers(db, auth.workspace.id),
        "webhook_urls": {
            "Resend": f"{base_url}/webhooks/{slug}/resend",
            "Cal.com": f"{base_url}/webhooks/{slug}/calcom",
            "Africa's Talking": at_url,
            "Twilio voice": f"{base_url}/webhooks/{slug}/voice",
            "Twilio WhatsApp": f"{base_url}/webhooks/{slug}/whatsapp",
        },
        "team": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "must_change_password": u.must_change_password,
                "last_login_at": _iso(u.last_login_at),
            }
            for u in team
        ],
        "llm_defaults": {
            "compose": settings.compose_model,
            "reply": settings.reply_model,
            "judge": settings.judge_model,
        },
        "killswitch_defaults": {
            "opt_out_rate": settings.killswitch_opt_out_rate,
            "bounce_rate": settings.killswitch_bounce_rate,
            "cost_per_qualified_lead":
                settings.killswitch_cost_per_qualified_lead_usd,
            "max_llm_cost_usd": settings.killswitch_max_llm_cost_usd,
        },
        "local_llm_configured": bool(settings.local_llm_base_url),
        "local_llm_base_url": settings.local_llm_base_url,
    }

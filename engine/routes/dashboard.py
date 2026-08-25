"""Operator dashboard pages: pipeline, campaigns, prospects, approvals,
analytics. Server-rendered; forms post to the action routes in api.py."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import AuthContext, current_auth
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
)
from engine.services.credentials import PROVIDER_FIELDS, configured_providers
from engine.services.killswitch import compute_metrics
from engine.templating import templates

router = APIRouter()


def _ctx(request: Request, auth: AuthContext, **extra) -> dict:
    return {
        "user": auth.user,
        "workspace": auth.workspace,
        "live_mode": get_settings().live_mode,
        "msg": request.query_params.get("msg", ""),
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    ws_id = auth.workspace.id
    stage_rows = await db.execute(
        select(Prospect.stage, func.count())
        .where(Prospect.workspace_id == ws_id)
        .group_by(Prospect.stage)
    )
    stage_counts = dict(stage_rows.all())
    pending_drafts = int((await db.execute(
        select(func.count()).select_from(Draft).where(
            Draft.workspace_id == ws_id, Draft.status == "pending_review"
        )
    )).scalar_one())
    upcoming = (await db.execute(
        select(Booking)
        .where(Booking.workspace_id == ws_id, Booking.status.in_(["confirmed", "rescheduled"]))
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
    return templates.TemplateResponse(
        request,
        "home.html",
        _ctx(
            request, auth,
            stages=PROSPECT_STAGES,
            stage_counts=stage_counts,
            pending_drafts=pending_drafts,
            upcoming=upcoming,
            escalations=escalations,
            metrics=metrics,
        ),
    )


@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    campaigns = (await db.execute(
        select(Campaign)
        .where(Campaign.workspace_id == auth.workspace.id)
        .order_by(Campaign.created_at.desc())
    )).scalars().all()
    counts: dict[str, int] = {}
    for c in campaigns:
        counts[c.id] = int((await db.execute(
            select(func.count()).select_from(Prospect).where(
                Prospect.campaign_id == c.id
            )
        )).scalar_one())
    return templates.TemplateResponse(
        request, "campaigns.html",
        _ctx(request, auth, campaigns=campaigns, counts=counts),
    )


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
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
    prospects = (await db.execute(
        select(Prospect)
        .where(Prospect.campaign_id == campaign.id)
        .order_by(Prospect.created_at.desc())
        .limit(200)
    )).scalars().all()
    return templates.TemplateResponse(
        request, "campaign_detail.html",
        _ctx(
            request, auth,
            campaign=campaign,
            stage_counts=dict(stage_rows.all()),
            stages=PROSPECT_STAGES,
            prospects=prospects,
        ),
    )


@router.get("/prospects", response_class=HTMLResponse)
async def prospects_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    stage = request.query_params.get("stage", "")
    query = select(Prospect).where(Prospect.workspace_id == auth.workspace.id)
    if stage and stage in PROSPECT_STAGES:
        query = query.where(Prospect.stage == stage)
    prospects = (await db.execute(
        query.order_by(Prospect.updated_at.desc()).limit(300)
    )).scalars().all()
    return templates.TemplateResponse(
        request, "prospects.html",
        _ctx(request, auth, prospects=prospects, stages=PROSPECT_STAGES,
             active_stage=stage),
    )


@router.get("/prospects/{prospect_id}", response_class=HTMLResponse)
async def prospect_detail(
    prospect_id: str,
    request: Request,
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
    return templates.TemplateResponse(
        request, "prospect_detail.html",
        _ctx(request, auth, prospect=prospect, timeline=timeline,
             drafts=drafts, bookings=bookings, stages=PROSPECT_STAGES),
    )


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    drafts = (await db.execute(
        select(Draft, Prospect)
        .join(Prospect, Draft.prospect_id == Prospect.id)
        .where(
            Draft.workspace_id == auth.workspace.id,
            Draft.status == "pending_review",
        )
        .order_by(Draft.created_at)
        .limit(100)
    )).all()
    return templates.TemplateResponse(
        request, "approvals.html", _ctx(request, auth, rows=drafts)
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
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
            Prospect.workspace_id == ws_id, Prospect.stage.in_(["warm", "booked"])
        )
    )).scalar_one())
    booked = int((await db.execute(
        select(func.count()).select_from(Booking).where(
            Booking.workspace_id == ws_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
        )
    )).scalar_one())
    funnel = [
        ("Emails sent", sent),
        ("Opened", opened),
        ("Replied (prospects)", replied),
        ("Warm / qualified", warm),
        ("Meetings booked", booked),
    ]
    return templates.TemplateResponse(
        request, "analytics.html",
        _ctx(request, auth, metrics=metrics, funnel=funnel,
             max_funnel=max([v for _, v in funnel] + [1])),
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    providers = await configured_providers(db, auth.workspace.id)
    settings = get_settings()
    base_url = settings.base_url
    slug = auth.workspace.slug
    llm_defaults = {
        "compose": settings.compose_model,
        "reply": settings.reply_model,
        "judge": settings.judge_model,
    }
    webhook_urls = {
        "Resend": f"{base_url}/webhooks/{slug}/resend",
        "Cal.com": f"{base_url}/webhooks/{slug}/calcom",
        "Africa's Talking": f"{base_url}/webhooks/{slug}/sms/<webhook_token>",
        "Twilio voice": f"{base_url}/webhooks/{slug}/voice",
    }
    return templates.TemplateResponse(
        request, "settings.html",
        _ctx(
            request, auth,
            provider_fields=PROVIDER_FIELDS,
            configured=providers,
            webhook_urls=webhook_urls,
            llm_defaults=llm_defaults,
            local_llm_configured=bool(settings.local_llm_base_url),
            local_llm_base_url=settings.local_llm_base_url,
            welcome=request.query_params.get("welcome", ""),
        ),
    )

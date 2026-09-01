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
    Job,
    Message,
    Prospect,
    User,
)
from engine.services.credentials import (
    PROVIDER_FIELDS,
    configured_providers,
    get_credentials,
)
from engine.services.dataset import dataset_available, matching_companies
from engine.services.killswitch import compute_metrics
from engine.templating import templates

router = APIRouter()

# Page sizes for the list pages (previously hard caps — anything past the
# cap was unreachable in the UI).
PROSPECTS_PAGE_SIZE = 300
CAMPAIGN_PROSPECTS_PAGE_SIZE = 200
APPROVALS_PAGE_SIZE = 100
JOBS_PAGE_SIZE = 50


async def _paged(
    db: AsyncSession, request: Request, query, page_size: int
):
    """Offset pagination driven by ?page=. Returns (Result, pager) where
    pager is the context for templates/_pager.html; the caller finishes
    with .scalars().all() or .all() as before."""
    from urllib.parse import urlencode

    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    total = int((await db.execute(
        select(func.count()).select_from(query.order_by(None).subquery())
    )).scalar_one())
    pages = max(1, -(-total // page_size))
    result = await db.execute(
        query.limit(page_size).offset((page - 1) * page_size)
    )
    keep = {
        k: v for k, v in request.query_params.items()
        if k not in ("page", "msg")
    }
    qs = urlencode(keep) + "&" if keep else ""
    return result, {"page": page, "pages": pages, "total": total, "qs": qs}


async def _ctx(
    request: Request, auth: AuthContext, db: AsyncSession, **extra
) -> dict:
    # Dead jobs are surfaced as a banner on every page (like a kill-switch
    # pause) — nobody should have to poll /jobs to learn the pipeline broke.
    dead_jobs = int((await db.execute(
        select(func.count()).select_from(Job).where(
            Job.workspace_id == auth.workspace.id, Job.status == "dead"
        )
    )).scalar_one())
    return {
        "user": auth.user,
        "workspace": auth.workspace,
        "live_mode": get_settings().live_mode,
        "msg": request.query_params.get("msg", ""),
        "dead_jobs": dead_jobs,
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
        await _ctx(
            request, auth, db,
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
    count_rows = await db.execute(
        select(Prospect.campaign_id, func.count())
        .where(Prospect.workspace_id == auth.workspace.id)
        .group_by(Prospect.campaign_id)
    )
    counts: dict[str, int] = {cid: int(n) for cid, n in count_rows.all() if cid}
    return templates.TemplateResponse(
        request, "campaigns.html",
        await _ctx(request, auth, db, campaigns=campaigns, counts=counts),
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
    result, pager = await _paged(
        db, request,
        select(Prospect)
        .where(Prospect.campaign_id == campaign.id)
        .order_by(Prospect.created_at.desc()),
        CAMPAIGN_PROSPECTS_PAGE_SIZE,
    )
    prospects = result.scalars().all()
    return templates.TemplateResponse(
        request, "campaign_detail.html",
        await _ctx(
            request, auth, db,
            campaign=campaign,
            stage_counts=dict(stage_rows.all()),
            stages=PROSPECT_STAGES,
            prospects=prospects,
            pager=pager,
            # Offer the bundled dataset only when it shipped, and say how
            # many match — an import button with an unknown result is worse
            # than no button.
            dataset_count=len(matching_companies()) if dataset_available() else 0,
        ),
    )


@router.get("/prospects", response_class=HTMLResponse)
async def prospects_page(
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
        # Escape LIKE wildcards so a literal % or _ in the search behaves.
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        query = query.where(
            Prospect.email.ilike(pattern, escape="\\")
            | Prospect.name.ilike(pattern, escape="\\")
            | Prospect.company.ilike(pattern, escape="\\")
        )
    result, pager = await _paged(
        db, request,
        query.order_by(Prospect.updated_at.desc()),
        PROSPECTS_PAGE_SIZE,
    )
    prospects = result.scalars().all()
    # The CSV import form lives on a campaign page, so this page needs a
    # campaign to point at — otherwise "Import prospects" lands on a list and
    # the user has to guess the form is nested inside one. Prefer an active
    # campaign; fall back to the oldest.
    import_campaign = (await db.execute(
        select(Campaign)
        .where(Campaign.workspace_id == auth.workspace.id)
        .order_by((Campaign.status != "active"), Campaign.created_at)
        .limit(1)
    )).scalars().first()
    return templates.TemplateResponse(
        request, "prospects.html",
        await _ctx(request, auth, db, prospects=prospects, stages=PROSPECT_STAGES,
             active_stage=stage, search=q, pager=pager,
             import_campaign=import_campaign),
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
        await _ctx(request, auth, db, prospect=prospect, timeline=timeline,
             drafts=drafts, bookings=bookings, stages=PROSPECT_STAGES),
    )


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page(
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
    drafts = result.all()
    return templates.TemplateResponse(
        request, "approvals.html",
        await _ctx(request, auth, db, rows=drafts, pager=pager),
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
    from engine.services import deliverability, learning

    angles = await learning.angle_performance(db, ws_id)
    calibration = await learning.judge_calibration(db, ws_id)
    edits = await learning.edit_stats(db, ws_id)
    delivery = await deliverability.summary(db, auth.workspace)
    return templates.TemplateResponse(
        request, "analytics.html",
        await _ctx(request, auth, db, metrics=metrics, funnel=funnel,
             max_funnel=max([v for _, v in funnel] + [1]),
             angles=angles, calibration=calibration, edits=edits,
             delivery=delivery),
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Queue health for this workspace: failing and dead jobs with their
    errors, so a stuck pipeline is visible without psql access."""
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
    problem_jobs = result.scalars().all()
    return templates.TemplateResponse(
        request, "jobs.html",
        await _ctx(request, auth, db,
             status_counts=dict(status_rows.all()),
             problem_jobs=problem_jobs, pager=pager),
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
    # The Africa's Talking webhook token is part of the URL the admin must
    # register in the AT dashboard — render the real URL for admins (it is
    # a URL auth token, not an API secret; without it the webhook can never
    # be registered and inbound SMS silently fails verification).
    at_url = f"{base_url}/webhooks/{slug}/sms/<webhook_token>"
    if auth.user.role == "admin":
        at_creds = await get_credentials(db, auth.workspace.id, "africastalking")
        if at_creds and at_creds.get("webhook_token"):
            at_url = f"{base_url}/webhooks/{slug}/sms/{at_creds['webhook_token']}"
    webhook_urls = {
        "Resend": f"{base_url}/webhooks/{slug}/resend",
        "Cal.com": f"{base_url}/webhooks/{slug}/calcom",
        "Africa's Talking": at_url,
        "Twilio voice": f"{base_url}/webhooks/{slug}/voice",
        "Twilio WhatsApp": f"{base_url}/webhooks/{slug}/whatsapp",
        "Telegram": f"{base_url}/webhooks/{slug}/telegram",
    }
    team = (await db.execute(
        select(User)
        .where(User.workspace_id == auth.workspace.id)
        .order_by(User.created_at)
    )).scalars().all()
    return templates.TemplateResponse(
        request, "settings.html",
        await _ctx(
            request, auth, db,
            provider_fields=PROVIDER_FIELDS,
            configured=providers,
            webhook_urls=webhook_urls,
            team=team,
            llm_defaults=llm_defaults,
            killswitch_defaults={
                "opt_out_rate": settings.killswitch_opt_out_rate,
                "bounce_rate": settings.killswitch_bounce_rate,
                "cost_per_qualified_lead":
                    settings.killswitch_cost_per_qualified_lead_usd,
                "max_llm_cost_usd": settings.killswitch_max_llm_cost_usd,
            },
            local_llm_configured=bool(settings.local_llm_base_url),
            local_llm_base_url=settings.local_llm_base_url,
            welcome=request.query_params.get("welcome", ""),
        ),
    )

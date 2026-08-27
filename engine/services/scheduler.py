"""Periodic scheduler: campaign send ticks, follow-ups, kill-switch checks,
and housekeeping (stuck-job recovery, retention purges).

Safety under scale-out: on Postgres a pass first takes an advisory lock, so
two replicas never run concurrent passes; enqueues are additionally
idempotency-keyed. Each workspace is processed in its own transaction so one
tenant's failure can't roll back another's pass.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text

from engine.auth import purge_expired_sessions
from engine.config import get_settings
from engine.db import db_session
from engine.models import (
    Booking,
    Campaign,
    DailyCounter,
    Prospect,
    WebhookEvent,
    Workspace,
    utcnow,
)
from engine.queue import beat, enqueue, purge_old_jobs, recover_stuck_jobs
from engine.services.enrichment import enrichment_configured
from engine.services.killswitch import evaluate_killswitch
from engine.services.suppression import SendBlocked, increment_daily_counter

logger = logging.getLogger(__name__)

_last_purge_date: str | None = None


def _campaign_now(campaign: Campaign) -> datetime:
    try:
        return datetime.now(ZoneInfo(campaign.timezone or "UTC"))
    except (KeyError, ValueError):
        # Write-time validation rejects bad zones now, but pre-existing rows
        # may carry one — fall back loudly, not silently.
        logger.warning(
            "Campaign %s has invalid timezone %r; using UTC",
            campaign.id, campaign.timezone,
        )
        return datetime.now(ZoneInfo("UTC"))


def _in_send_window(campaign: Campaign) -> bool:
    now = _campaign_now(campaign)
    start, end = campaign.send_window_start_hour, campaign.send_window_end_hour
    if start == end:
        return False  # degenerate window (rejected at write time) — closed
    if start < end:
        return start <= now.hour < end
    # Overnight window (e.g. 18 → 8): open from start through midnight to end.
    return now.hour >= start or now.hour < end


def _campaign_today(campaign: Campaign) -> str:
    """The campaign's local calendar day — the daily cap must reset at local
    midnight, not UTC midnight (which can fall inside the send window and
    allow 2× the cap in one local day)."""
    return _campaign_now(campaign).date().isoformat()


def _queue_bucket(campaign: Campaign) -> str:
    return f"q:{campaign.id}"


async def _queued_today(db, campaign: Campaign) -> int:
    row = await db.execute(
        select(DailyCounter.count).where(
            DailyCounter.workspace_id == campaign.workspace_id,
            DailyCounter.date == _campaign_today(campaign),
            DailyCounter.channel == _queue_bucket(campaign),
        )
    )
    return int(row.scalar_one_or_none() or 0)


# Enrichment jobs enqueued per campaign per pass — enrichment doesn't count
# against the campaign daily_cap (only composition does).
ENRICH_BATCH = 50


async def _tick_enrichment(db, campaign: Campaign) -> None:
    """Queue signal enrichment for 'new' prospects when the workspace has an
    enrichment source configured. Prospects come back 'enriched' (with
    whatever signals the source produced) and get composed on a later pass."""
    rows = await db.execute(
        select(Prospect)
        .where(
            Prospect.campaign_id == campaign.id,
            Prospect.stage == "new",
        )
        .order_by(Prospect.created_at)
        .limit(ENRICH_BATCH)
    )
    for prospect in rows.scalars().all():
        await enqueue(
            db,
            "enrich_prospect",
            {
                "workspace_id": campaign.workspace_id,
                "prospect_id": prospect.id,
            },
            workspace_id=campaign.workspace_id,
            # One enrichment per prospect; retries happen inside the job.
            idempotency_key=f"enrich:{prospect.id}",
        )


async def _tick_campaign(db, campaign: Campaign, *, enrich: bool) -> None:
    """Move new/enriched prospects into composition, at most daily_cap per
    calendar day (tracked in DailyCounter — a 60s tick must not treat the
    cap as per-tick)."""
    if not _in_send_window(campaign):
        return
    if enrich:
        await _tick_enrichment(db, campaign)
    remaining = campaign.daily_cap - await _queued_today(db, campaign)
    if remaining <= 0:
        return
    # With an enrichment source configured, 'new' prospects wait for their
    # signals; without one they compose directly (inquiry mode, as before).
    compose_stages = ["enriched"] if enrich else ["new", "enriched"]
    rows = await db.execute(
        select(Prospect)
        .where(
            Prospect.campaign_id == campaign.id,
            Prospect.stage.in_(compose_stages),
        )
        .order_by(Prospect.created_at)
        .limit(remaining)
    )
    for prospect in rows.scalars().all():
        try:
            await increment_daily_counter(
                db, campaign.workspace_id, _queue_bucket(campaign),
                cap=campaign.daily_cap,
                date_key=_campaign_today(campaign),
            )
        except SendBlocked:
            return  # today's budget spent
        await enqueue(
            db,
            "compose_draft",
            {
                "workspace_id": campaign.workspace_id,
                "prospect_id": prospect.id,
                "campaign_id": campaign.id,
                "touch_number": 1,
            },
            workspace_id=campaign.workspace_id,
            # One first-touch compose per prospect, ever.
            idempotency_key=f"compose:{prospect.id}:t1",
        )
        prospect.stage = "queued"


async def _tick_followups(db, campaign: Campaign) -> None:
    # Follow-ups honor the campaign send window just like first touches — a
    # due follow-up outside the window simply waits for the next in-window
    # pass (next_followup_at stays set until then).
    if not _in_send_window(campaign):
        return
    rows = await db.execute(
        select(Prospect).where(
            Prospect.campaign_id == campaign.id,
            Prospect.stage == "contacted",
            Prospect.next_followup_at.is_not(None),
            Prospect.next_followup_at <= utcnow(),
        )
    )
    for prospect in rows.scalars().all():
        if prospect.touch_count < 1:
            # No recorded send (e.g. a manual stage change): there is nothing
            # to follow up on, and steps[touch_count - 1] would silently wrap
            # to the LAST sequence step. Clear the stray schedule instead.
            logger.warning(
                "Prospect %s has a follow-up scheduled but no sends; clearing",
                prospect.id,
            )
            prospect.next_followup_at = None
            continue
        touch = prospect.touch_count + 1
        steps = campaign.sequence or []
        angle = ""
        if prospect.touch_count - 1 < len(steps):
            angle = str(steps[prospect.touch_count - 1].get("angle", ""))
        await enqueue(
            db,
            "compose_draft",
            {
                "workspace_id": campaign.workspace_id,
                "prospect_id": prospect.id,
                "campaign_id": campaign.id,
                "touch_number": touch,
                "angle": angle,
            },
            workspace_id=campaign.workspace_id,
            idempotency_key=f"compose:{prospect.id}:t{touch}",
        )
        prospect.next_followup_at = None  # re-set when the follow-up is sent


# Reminders go out when a confirmed booking is this close.
REMINDER_HOURS_AHEAD = 24


async def _tick_reminders(db, workspace: Workspace) -> None:
    """Queue SMS reminders for bookings starting within the next day."""
    now = utcnow()
    rows = await db.execute(
        select(Booking).where(
            Booking.workspace_id == workspace.id,
            Booking.status.in_(["confirmed", "rescheduled"]),
            Booking.prospect_id.is_not(None),
            Booking.start_time.is_not(None),
            Booking.start_time > now,
            Booking.start_time <= now + timedelta(hours=REMINDER_HOURS_AHEAD),
        )
    )
    for booking in rows.scalars().all():
        await enqueue(
            db,
            "booking_reminder",
            {
                "workspace_id": workspace.id,
                "prospect_id": booking.prospect_id,
                "booking_id": booking.id,
            },
            workspace_id=workspace.id,
            # One reminder per booking, ever (rescheduling changes nothing —
            # the reminder reads the current start time when it runs).
            idempotency_key=f"remind:{booking.id}",
        )


async def _tick_digest(db, workspace: Workspace) -> None:
    """Queue the weekly ROI digest on Mondays, once per ISO week."""
    settings = get_settings()
    if not settings.weekly_digest_enabled:
        return
    now = utcnow()
    if now.weekday() != 0:  # Monday
        return
    iso = now.isocalendar()
    await enqueue(
        db,
        "weekly_digest",
        {"workspace_id": workspace.id},
        workspace_id=workspace.id,
        idempotency_key=f"digest:{workspace.id}:{iso.year}-w{iso.week}",
    )


async def _process_workspace(workspace_id: str) -> None:
    async with db_session() as db:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            return
        await evaluate_killswitch(db, workspace)
        await _tick_reminders(db, workspace)
        await _tick_digest(db, workspace)
        if workspace.outbound_paused:
            return
        campaigns = (
            await db.execute(
                select(Campaign).where(
                    Campaign.workspace_id == workspace.id,
                    Campaign.status == "active",
                )
            )
        ).scalars().all()
        enrich = await enrichment_configured(db, workspace.id)
        for campaign in campaigns:
            await _tick_campaign(db, campaign, enrich=enrich)
            await _tick_followups(db, campaign)


async def run_scheduler_pass() -> None:
    async with db_session() as lock_db:
        if lock_db.get_bind().dialect.name == "postgresql":
            got = (await lock_db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext('engine-scheduler'))")
            )).scalar()
            if not got:
                logger.debug("Another scheduler instance holds the lock; skipping")
                return
        workspace_ids = [
            wid for (wid,) in
            (await lock_db.execute(select(Workspace.id))).all()
        ]
        # One transaction per workspace: a failing tenant is isolated and
        # logged, and every other tenant's tick still commits.
        for workspace_id in workspace_ids:
            try:
                await _process_workspace(workspace_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Scheduler pass failed for workspace %s", workspace_id
                )
        await _housekeeping()
        # advisory lock releases when lock_db's transaction ends here


async def _housekeeping() -> None:
    global _last_purge_date
    try:
        await recover_stuck_jobs()
    except Exception:  # noqa: BLE001
        logger.exception("Stuck-job recovery failed")

    today = utcnow().date().isoformat()
    if _last_purge_date == today:
        return
    _last_purge_date = today
    settings = get_settings()
    try:
        removed = await purge_old_jobs()
        async with db_session() as db:
            purged_sessions = await purge_expired_sessions(db)
            if settings.retention_webhook_events_days > 0:
                cutoff = utcnow() - timedelta(
                    days=settings.retention_webhook_events_days
                )
                await db.execute(
                    delete(WebhookEvent).where(WebhookEvent.received_at < cutoff)
                )
            if settings.retention_daily_counters_days > 0:
                cutoff_date = (
                    utcnow() - timedelta(days=settings.retention_daily_counters_days)
                ).date().isoformat()
                await db.execute(
                    delete(DailyCounter).where(DailyCounter.date < cutoff_date)
                )
        logger.info(
            "Retention purge: %d old jobs, %d expired sessions",
            removed, purged_sessions,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Retention purge failed")


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    logger.info(
        "Scheduler started (every %.0fs)", settings.scheduler_interval_seconds
    )
    while not stop_event.is_set():
        beat("scheduler")
        try:
            await run_scheduler_pass()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover
            logger.exception("Scheduler pass failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.scheduler_interval_seconds
            )
        except TimeoutError:
            pass

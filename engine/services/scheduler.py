"""Periodic scheduler: campaign send ticks, follow-ups, kill-switch checks.

Runs inside the worker process on a fixed interval. All actions are enqueued
as idempotent jobs, so overlapping ticks (or two schedulers during a deploy)
cannot double-send.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from engine.config import get_settings
from engine.db import db_session
from engine.models import Campaign, Prospect, Workspace, utcnow
from engine.queue import enqueue
from engine.services.killswitch import evaluate_killswitch

logger = logging.getLogger(__name__)


def _in_send_window(campaign: Campaign) -> bool:
    try:
        now = datetime.now(ZoneInfo(campaign.timezone or "UTC"))
    except Exception:
        now = datetime.now(ZoneInfo("UTC"))
    return campaign.send_window_start_hour <= now.hour < campaign.send_window_end_hour


async def _tick_campaign(db, campaign: Campaign) -> None:
    """Move up to daily_cap enriched/new prospects into composition today."""
    if not _in_send_window(campaign):
        return
    today = utcnow().date().isoformat()
    rows = await db.execute(
        select(Prospect)
        .where(
            Prospect.campaign_id == campaign.id,
            Prospect.stage.in_(["new", "enriched"]),
        )
        .order_by(Prospect.created_at)
        .limit(campaign.daily_cap)
    )
    for prospect in rows.scalars().all():
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
    _ = today  # (kept for symmetry with follow-up keys below)


async def _tick_followups(db, campaign: Campaign) -> None:
    rows = await db.execute(
        select(Prospect).where(
            Prospect.campaign_id == campaign.id,
            Prospect.stage == "contacted",
            Prospect.next_followup_at.is_not(None),
            Prospect.next_followup_at <= utcnow(),
        )
    )
    for prospect in rows.scalars().all():
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


async def run_scheduler_pass() -> None:
    async with db_session() as db:
        workspaces = (await db.execute(select(Workspace))).scalars().all()
        for workspace in workspaces:
            await evaluate_killswitch(db, workspace)
            if workspace.outbound_paused:
                continue
            campaigns = (
                await db.execute(
                    select(Campaign).where(
                        Campaign.workspace_id == workspace.id,
                        Campaign.status == "active",
                    )
                )
            ).scalars().all()
            for campaign in campaigns:
                await _tick_campaign(db, campaign)
                await _tick_followups(db, campaign)


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    logger.info(
        "Scheduler started (every %.0fs)", settings.scheduler_interval_seconds
    )
    while not stop_event.is_set():
        try:
            await run_scheduler_pass()
        except Exception:  # pragma: no cover
            logger.exception("Scheduler pass failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.scheduler_interval_seconds
            )
        except asyncio.TimeoutError:
            pass

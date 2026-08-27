"""Email deliverability autopilot: domain warm-up ramping.

A fresh sending domain that blasts its full daily cap on day one lands in
spam and burns the domain. The effective email cap therefore ramps from
WARMUP_START_PER_DAY on the day of the workspace's first outbound email,
growing WARMUP_DAILY_GROWTH× per day until it reaches the configured cap.
The kill-switch remains the reactive guard (bounce/complaint rates); this is
the proactive one.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.models import Message, Workspace, as_aware, utcnow

logger = logging.getLogger(__name__)


async def _first_outbound_at(db: AsyncSession, workspace_id: str):
    """Warm-up epoch: the workspace's first outbound email, OR the moment
    the sending address last changed — a brand-new domain must not inherit
    the old domain's fully-ramped cap."""
    from engine.models import AuditLog

    first = (await db.execute(
        select(func.min(Message.created_at)).where(
            Message.workspace_id == workspace_id,
            Message.channel == "email",
            Message.direction == "out",
        )
    )).scalar_one()
    if first is None:
        return None
    last_change = (await db.execute(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.workspace_id == workspace_id,
            AuditLog.action == "workspace_updated",
        )
    )).scalar_one()
    if last_change is not None and as_aware(last_change) > as_aware(first):
        return last_change
    return first


async def warmup_email_cap(db: AsyncSession, workspace: Workspace) -> int:
    """Today's effective email cap for this workspace under warm-up."""
    settings = get_settings()
    full_cap = settings.max_emails_per_day_per_workspace
    if not settings.warmup_enabled:
        return full_cap
    first = await _first_outbound_at(db, workspace.id)
    days = 0 if first is None else max(0, (utcnow() - as_aware(first)).days)
    ramped = int(settings.warmup_start_per_day * (settings.warmup_daily_growth ** days))
    return min(full_cap, max(1, ramped))


async def summary(db: AsyncSession, workspace: Workspace) -> dict:
    """Deliverability panel data: warm-up state + recent bounce/complaint
    counts (the same events the kill-switch rates are built from)."""
    from datetime import timedelta

    settings = get_settings()
    first = await _first_outbound_at(db, workspace.id)
    days = 0 if first is None else max(0, (utcnow() - as_aware(first)).days)
    cap_today = await warmup_email_cap(db, workspace)
    since = utcnow() - timedelta(days=7)

    async def _count(status: str) -> int:
        return int((await db.execute(
            select(func.count()).select_from(Message).where(
                Message.workspace_id == workspace.id,
                Message.channel == "email",
                Message.status == status,
                Message.created_at >= since,
            )
        )).scalar_one())

    return {
        "warmup_enabled": settings.warmup_enabled,
        "warmup_day": days,
        "cap_today": cap_today,
        "full_cap": settings.max_emails_per_day_per_workspace,
        "warmed_up": cap_today >= settings.max_emails_per_day_per_workspace,
        "bounced_7d": await _count("bounced"),
        "complained_7d": await _count("complained"),
    }

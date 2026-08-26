"""Durable suppression (do-not-contact) list and daily volume caps.

Every outbound send MUST pass through check_can_send() — it enforces, in
order: workspace pause (kill-switch), suppression list, per-prospect touch
ceiling, and the workspace's daily channel cap.
"""
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.models import DailyCounter, Prospect, Suppression, Workspace, utcnow

logger = logging.getLogger(__name__)


class SendBlocked(Exception):
    """Raised when policy forbids an outbound send. Not retryable."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def normalize_email(addr: str) -> str:
    return addr.strip().lower()


def normalize_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "").replace("-", "")
    if p and not p.startswith("+") and p.isdigit():
        p = "+" + p
    return p


async def is_suppressed(
    db: AsyncSession, workspace_id: str, channel: str, address: str
) -> bool:
    address = (
        normalize_email(address) if channel == "email" else normalize_phone(address)
    )
    row = await db.execute(
        select(Suppression.id).where(
            Suppression.workspace_id == workspace_id,
            Suppression.channel == channel,
            Suppression.address == address,
        )
    )
    return row.first() is not None


async def suppress(
    db: AsyncSession, workspace_id: str, channel: str, address: str, reason: str
) -> None:
    address = (
        normalize_email(address) if channel == "email" else normalize_phone(address)
    )
    if not address:
        return
    try:
        # SAVEPOINT: a duplicate must not roll back the caller's transaction.
        async with db.begin_nested():
            db.add(
                Suppression(
                    workspace_id=workspace_id, channel=channel,
                    address=address, reason=reason,
                )
            )
            await db.flush()
        logger.info(
            "Suppressed %s/%s in workspace %s (%s)",
            channel, address, workspace_id, reason,
        )
    except IntegrityError:
        pass  # already suppressed — idempotent


async def unsuppress(
    db: AsyncSession, workspace_id: str, channel: str, address: str
) -> None:
    address = (
        normalize_email(address) if channel == "email" else normalize_phone(address)
    )
    row = await db.execute(
        select(Suppression).where(
            Suppression.workspace_id == workspace_id,
            Suppression.channel == channel,
            Suppression.address == address,
        )
    )
    entry = row.scalar_one_or_none()
    if entry is not None:
        await db.delete(entry)


async def increment_daily_counter(
    db: AsyncSession, workspace_id: str, channel: str, cap: int, amount: int = 1
) -> None:
    """Atomically increment the day's counter, enforcing the cap in SQL.

    The conditional UPDATE (`count + amount <= cap`) is evaluated under the
    row lock, so two concurrent workers cannot both pass a read-then-write
    check and overshoot the ceiling."""
    today = utcnow().date().isoformat()
    try:
        async with db.begin_nested():
            db.add(DailyCounter(
                workspace_id=workspace_id, date=today, channel=channel, count=0
            ))
            await db.flush()
    except IntegrityError:
        pass  # row already exists for today
    result = await db.execute(
        update(DailyCounter)
        .where(
            DailyCounter.workspace_id == workspace_id,
            DailyCounter.date == today,
            DailyCounter.channel == channel,
            DailyCounter.count + amount <= cap,
        )
        .values(count=DailyCounter.count + amount)
    )
    if not result.rowcount:
        raise SendBlocked(f"Daily {channel} cap reached ({cap}) for this workspace")


async def check_can_send(
    db: AsyncSession,
    workspace: Workspace,
    channel: str,
    address: str,
    prospect: Prospect | None = None,
) -> None:
    """Raise SendBlocked unless this outbound send is allowed.
    On success, the daily counter has been incremented (call within the same
    transaction as the send record)."""
    settings = get_settings()

    if workspace.outbound_paused:
        raise SendBlocked(
            f"Workspace outbound is paused: {workspace.pause_reason or 'manual pause'}"
        )
    if await is_suppressed(db, workspace.id, channel, address):
        raise SendBlocked(f"Recipient is on the {channel} suppression list")
    if prospect is not None and prospect.touch_count >= settings.max_touches_per_prospect:
        raise SendBlocked(
            f"Prospect reached the touch ceiling "
            f"({settings.max_touches_per_prospect})"
        )
    cap = (
        settings.max_emails_per_day_per_workspace
        if channel == "email"
        else settings.max_sms_per_day_per_workspace
    )
    await increment_daily_counter(db, workspace.id, channel, cap)

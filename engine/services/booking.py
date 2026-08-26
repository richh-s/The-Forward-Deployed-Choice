"""Cal.com booking links and booking-event handling."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Booking, Prospect, Workspace

logger = logging.getLogger(__name__)


def booking_url_for(workspace: Workspace, prospect: Prospect) -> str | None:
    """Personalized Cal.com booking URL: pre-fills the attendee and carries the
    prospect id in metadata so the booking webhook can close the loop."""
    base = (workspace.calcom_event_url or "").rstrip("/")
    if not base:
        return None
    from urllib.parse import urlencode

    params = {
        "name": prospect.name or "",
        "email": prospect.email,
        "metadata[prospect_id]": prospect.id,
        "metadata[workspace_id]": workspace.id,
    }
    return f"{base}?{urlencode({k: v for k, v in params.items() if v})}"


def _parse_start(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def record_booking_event(
    db: AsyncSession, workspace: Workspace, trigger: str, payload: dict
) -> Booking | None:
    """Persist a Cal.com booking lifecycle event and advance the prospect.
    Idempotent per (workspace, booking uid)."""
    uid = str(payload.get("uid") or "")
    if not uid:
        logger.warning("Cal.com event %s without uid; ignoring", trigger)
        return None

    metadata = payload.get("metadata") or {}
    prospect: Prospect | None = None
    prospect_id = metadata.get("prospect_id")
    if prospect_id:
        prospect = await db.get(Prospect, prospect_id)
        # metadata is attacker-controllable webhook input — never let it
        # reference a prospect outside this workspace.
        if prospect is not None and prospect.workspace_id != workspace.id:
            logger.warning(
                "Cal.com metadata prospect_id %s not in workspace %s; ignoring",
                prospect_id, workspace.id,
            )
            prospect = None
    if prospect is None:
        # Fall back to attendee email lookup within the workspace.
        for attendee in payload.get("attendees") or []:
            email = (attendee.get("email") or "").lower().strip()
            if not email:
                continue
            row = await db.execute(
                select(Prospect).where(
                    Prospect.workspace_id == workspace.id,
                    Prospect.email == email,
                )
            )
            prospect = row.scalar_one_or_none()
            if prospect:
                break

    row = await db.execute(
        select(Booking).where(
            Booking.workspace_id == workspace.id, Booking.provider_uid == uid
        )
    )
    booking = row.scalar_one_or_none()
    status_map = {
        "BOOKING_CREATED": "confirmed",
        "BOOKING_RESCHEDULED": "rescheduled",
        "BOOKING_CANCELLED": "cancelled",
    }
    status = status_map.get(trigger, "confirmed")

    if booking is None:
        booking = Booking(
            workspace_id=workspace.id,
            prospect_id=prospect.id if prospect else None,
            provider_uid=uid,
            start_time=_parse_start(payload.get("startTime")),
            status=status,
            meta={"title": payload.get("title", "")},
        )
        db.add(booking)
    else:
        booking.status = status
        booking.start_time = _parse_start(payload.get("startTime")) or booking.start_time

    if prospect and status in ("confirmed", "rescheduled"):
        prospect.stage = "booked"
    elif prospect and status == "cancelled" and prospect.stage == "booked":
        prospect.stage = "warm"
    await db.flush()
    return booking

"""Rate limiting shared across every instance.

Counts live in the `rate_limit_counters` table rather than process memory.
That matters as soon as the web tier runs more than one instance: an
in-memory limiter grants each instance the full allowance (N instances = N x
the configured limit), and a deploy or restart clears every lockout — so an
attacker gets a fresh budget for free. The guarded endpoints (login, setup,
unsubscribe) are low-volume, so one upsert per request costs far less than
the bcrypt verification it is protecting.

Fixed window, not sliding: a client can burst up to 2x the limit across a
window boundary. That is the standard trade for a counter that stays correct
across instances without a sorted set, and these limits exist for abuse
resistance, not precise quota accounting.

Every count is written in its OWN committed transaction, deliberately.
Sharing the request's session would roll the increment back whenever the
request fails — and a failed login is exactly the event that must be counted.
"""
import logging
import time

from fastapi import HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from engine.config import get_settings
from engine.db import db_session
from engine.models import RateLimitCounter

logger = logging.getLogger(__name__)


async def _hit(bucket: str, window_seconds: float) -> int:
    """Increment `bucket`'s counter for the current window; return the new
    count. Returns 0 if the store is unreachable — see _allow()."""
    window_start = int(time.time() // window_seconds) * int(window_seconds)
    async with db_session() as db:
        # UPDATE-first, INSERT-on-miss: the update is atomic at the row level,
        # so concurrent requests serialise on it rather than lost-updating.
        result = await db.execute(
            update(RateLimitCounter)
            .where(
                RateLimitCounter.bucket == bucket,
                RateLimitCounter.window_start == window_start,
            )
            .values(count=RateLimitCounter.count + 1)
            .returning(RateLimitCounter.count)
        )
        row = result.first()
        if row is not None:
            return int(row[0])
        try:
            async with db.begin_nested():
                db.add(RateLimitCounter(
                    bucket=bucket, window_start=window_start, count=1
                ))
                await db.flush()
            return 1
        except IntegrityError:
            # Another request created the row between our UPDATE and INSERT.
            again = await db.execute(
                update(RateLimitCounter)
                .where(
                    RateLimitCounter.bucket == bucket,
                    RateLimitCounter.window_start == window_start,
                )
                .values(count=RateLimitCounter.count + 1)
                .returning(RateLimitCounter.count)
            )
            row = again.first()
            return int(row[0]) if row else 1


async def _allow(name: str, key: str, max_events: int, window: float) -> bool:
    try:
        count = await _hit(f"{name}:{key}", window)
    except Exception as exc:  # noqa: BLE001
        # Fail OPEN. These limiters guard availability, not correctness — a
        # database blip must not lock every user out of logging in. The
        # password check, CSRF, and signature verification all still apply.
        logger.warning("Rate limiter unavailable (%s); allowing request", exc)
        return True
    return count <= max_events


def client_ip(request: Request) -> str:
    # uvicorn is run with --proxy-headers behind the platform proxy, so
    # request.client reflects X-Forwarded-For from the trusted hop.
    return request.client.host if request.client else "unknown"


async def check_login_rate(request: Request, email: str) -> None:
    """Throttle by IP and by IP+account so neither a spray across accounts
    nor a focused attack on one account gets unlimited bcrypt attempts."""
    settings = get_settings()
    ip = client_ip(request)
    window = settings.login_rate_limit_window_seconds
    attempts = settings.login_rate_limit_attempts
    ok_ip = await _allow("login-ip", ip, attempts * 4, window)
    ok_target = await _allow("login-target", f"{ip}:{email.lower()}", attempts, window)
    if not (ok_ip and ok_target):
        raise HTTPException(
            status_code=429, detail="Too many login attempts; try again later"
        )


async def check_public_rate(request: Request, bucket: str) -> None:
    """Generic throttle for unauthenticated endpoints (/u/*, /setup)."""
    settings = get_settings()
    if not await _allow(
        f"public-{bucket}",
        client_ip(request),
        settings.public_rate_limit_requests,
        settings.public_rate_limit_window_seconds,
    ):
        raise HTTPException(status_code=429, detail="Too many requests")


async def purge_expired(older_than_seconds: float = 86_400) -> int:
    """Drop counters whose window closed long ago. Called by housekeeping so
    the table does not grow without bound."""
    cutoff = int(time.time() - older_than_seconds)
    async with db_session() as db:
        result = await db.execute(
            delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff)
        )
        return result.rowcount or 0


async def reset_all() -> None:
    """Test helper: clear every counter."""
    async with db_session() as db:
        await db.execute(delete(RateLimitCounter))


async def current_count(bucket: str, window_seconds: float) -> int:
    """Introspection helper for tests and debugging."""
    window_start = int(time.time() // window_seconds) * int(window_seconds)
    async with db_session() as db:
        row = (await db.execute(
            select(RateLimitCounter.count).where(
                RateLimitCounter.bucket == bucket,
                RateLimitCounter.window_start == window_start,
            )
        )).first()
        return int(row[0]) if row else 0

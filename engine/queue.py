"""Postgres-backed job queue.

Why a DB queue instead of Redis/Celery: one less piece of infrastructure for
the operator, and the volumes here (hundreds of sends/day per workspace) are
far below what a SKIP LOCKED queue handles comfortably. Webhook handlers
enqueue and return immediately; the worker loop performs side effects with
retries and exponential backoff. Jobs carry an optional idempotency key so
webhook retries never enqueue duplicate side effects.
"""
import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.db import db_session
from engine.models import Job, utcnow

logger = logging.getLogger(__name__)

JobHandler = Callable[[AsyncSession, Job], Awaitable[None]]
_handlers: dict[str, JobHandler] = {}


def job_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def register(fn: JobHandler) -> JobHandler:
        _handlers[job_type] = fn
        return fn
    return register


async def enqueue(
    db: AsyncSession,
    job_type: str,
    payload: dict,
    *,
    workspace_id: str | None = None,
    run_after_seconds: float = 0,
    idempotency_key: str | None = None,
    max_attempts: int | None = None,
) -> Job | None:
    """Insert a job. Returns None if the idempotency key already exists."""
    job = Job(
        workspace_id=workspace_id,
        type=job_type,
        payload=payload,
        run_after=utcnow() + timedelta(seconds=run_after_seconds),
        idempotency_key=idempotency_key,
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.info("Duplicate job suppressed: %s (%s)", job_type, idempotency_key)
        return None
    return job


async def _claim_one(db: AsyncSession) -> Job | None:
    """Claim the next runnable job. SKIP LOCKED makes this multi-worker safe
    on Postgres; on SQLite (tests/dev) it degrades to a plain select, which is
    fine for a single process."""
    stmt = (
        select(Job)
        .where(Job.status.in_(["pending", "failed"]), Job.run_after <= utcnow())
        .order_by(Job.run_after)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    await db.flush()
    return job


async def process_one() -> bool:
    """Run a single job to completion. Returns False when the queue is empty."""
    async with db_session() as db:
        job = await _claim_one(db)
        if job is None:
            return False
        job_id, job_type, attempts, max_attempts = (
            job.id, job.type, job.attempts, job.max_attempts,
        )
        # Commit the claim so a crash mid-job leaves it visibly 'running'.
    handler = _handlers.get(job_type)
    try:
        if handler is None:
            raise RuntimeError(f"No handler registered for job type {job_type!r}")
        async with db_session() as db:
            job = await db.get(Job, job_id)
            await handler(db, job)
            job.status = "done"
    except Exception as exc:  # noqa: BLE001 — the queue is the failure boundary
        backoff = min(3600, 30 * (2 ** (attempts - 1)))
        status = "failed" if attempts < max_attempts else "dead"
        logger.error(
            "Job %s (%s) attempt %d/%d failed: %s",
            job_id, job_type, attempts, max_attempts, exc,
        )
        async with db_session() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=status,
                    last_error=f"{exc}\n{traceback.format_exc()[-2000:]}",
                    run_after=utcnow() + timedelta(seconds=backoff),
                )
            )
    return True


async def worker_loop(stop_event: asyncio.Event) -> None:
    """Long-running worker: drain the queue, then poll."""
    settings = get_settings()
    logger.info("Job worker started (poll every %.1fs)", settings.worker_poll_seconds)
    while not stop_event.is_set():
        try:
            worked = await process_one()
        except Exception:  # pragma: no cover — engine-level failure
            logger.exception("Worker iteration crashed; backing off")
            worked = False
        if not worked:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.worker_poll_seconds
                )
            except asyncio.TimeoutError:
                pass


async def recover_stuck_jobs(older_than_minutes: int = 15) -> int:
    """Requeue jobs stuck in 'running' (e.g. process died mid-job)."""
    async with db_session() as db:
        result = await db.execute(
            update(Job)
            .where(
                Job.status == "running",
                Job.updated_at < utcnow() - timedelta(minutes=older_than_minutes),
            )
            .values(status="failed")
        )
        return result.rowcount or 0

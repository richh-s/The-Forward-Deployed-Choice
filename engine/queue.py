"""Postgres-backed job queue.

Why a DB queue instead of Redis/Celery: one less piece of infrastructure for
the operator, and the volumes here (hundreds of sends/day per workspace) are
far below what a SKIP LOCKED queue handles comfortably. Webhook handlers
enqueue and return immediately; the worker loop performs side effects with
retries and exponential backoff. Jobs carry an optional idempotency key so
webhook retries never enqueue duplicate side effects.

Transactional discipline: enqueue() absorbs a duplicate idempotency key
inside a SAVEPOINT, so the caller's transaction (which may already hold a
sent-email record) is never rolled back by a benign duplicate.
"""
import asyncio
import logging
import random
import traceback
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.db import db_session
from engine.models import Job, utcnow

logger = logging.getLogger(__name__)

JobHandler = Callable[[AsyncSession, Job], Awaitable[None]]
_handlers: dict[str, JobHandler] = {}

# Liveness heartbeats, read by /health: loop name → last-iteration time.
heartbeats: dict[str, object] = {}


def beat(name: str) -> None:
    heartbeats[name] = utcnow()


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
    """Insert a job. Returns None if the idempotency key already exists.

    A duplicate key only rolls back the SAVEPOINT around this insert — the
    caller's transaction (and everything already flushed in it) survives.
    """
    job = Job(
        workspace_id=workspace_id,
        type=job_type,
        payload=payload,
        run_after=utcnow() + timedelta(seconds=run_after_seconds),
        idempotency_key=idempotency_key,
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
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


def _backoff_seconds(attempts: int) -> float:
    base = min(3600, 30 * (2 ** (attempts - 1)))
    return base * random.uniform(0.8, 1.2)  # jitter — avoid retry stampedes


async def _record_failure(
    job_id: str, job_type: str, attempts: int, max_attempts: int, error: str
) -> None:
    status = "failed" if attempts < max_attempts else "dead"
    async with db_session() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=status,
                last_error=error[-4000:],
                run_after=utcnow() + timedelta(seconds=_backoff_seconds(attempts)),
            )
        )


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
            if job is None:  # reaped/deleted between claim and execution
                logger.warning("Job %s vanished after claim; skipping", job_id)
                return True
            await handler(db, job)
            job.status = "done"
    except asyncio.CancelledError:
        # Shutdown while mid-job: hand the job back to the queue immediately
        # rather than leaving it 'running' until the reaper finds it.
        # Don't burn a retry attempt — the job didn't fail.
        with_shield = asyncio.shield(_requeue_cancelled(job_id))
        try:
            await asyncio.wait_for(with_shield, timeout=5)
        except Exception:  # noqa: BLE001 — best effort during shutdown
            logger.warning("Could not requeue job %s on shutdown", job_id)
        raise
    except Exception as exc:  # noqa: BLE001 — the queue is the failure boundary
        logger.error(
            "Job %s (%s) attempt %d/%d failed: %s",
            job_id, job_type, attempts, max_attempts, exc,
        )
        await _record_failure(
            job_id, job_type, attempts, max_attempts,
            f"{exc}\n{traceback.format_exc()[-2000:]}",
        )
    return True


async def _requeue_cancelled(job_id: str) -> None:
    async with db_session() as db:
        # The attempt spent on this execution shouldn't count against the job.
        await db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                status="failed",
                run_after=utcnow(),
                last_error="requeued: worker shutdown mid-job",
                attempts=Job.attempts - 1,
            )
        )


async def worker_loop(stop_event: asyncio.Event, name: str = "worker") -> None:
    """Long-running worker: drain the queue, then poll."""
    settings = get_settings()
    logger.info(
        "Job worker %s started (poll every %.1fs)", name, settings.worker_poll_seconds
    )
    while not stop_event.is_set():
        beat(name)
        try:
            worked = await process_one()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover — engine-level failure
            logger.exception("Worker iteration crashed; backing off")
            worked = False
        if not worked:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.worker_poll_seconds
                )
            except TimeoutError:
                pass


async def recover_stuck_jobs(older_than_minutes: int | None = None) -> int:
    """Requeue jobs stuck in 'running' (e.g. process died mid-job).
    Jobs already at their attempt budget go to 'dead' instead of getting
    a bonus execution."""
    minutes = older_than_minutes or get_settings().job_stuck_after_minutes
    cutoff = utcnow() - timedelta(minutes=minutes)
    async with db_session() as db:
        dead = await db.execute(
            update(Job)
            .where(
                Job.status == "running",
                Job.updated_at < cutoff,
                Job.attempts >= Job.max_attempts,
            )
            .values(status="dead", last_error="stuck in running at attempt budget")
        )
        requeued = await db.execute(
            update(Job)
            .where(Job.status == "running", Job.updated_at < cutoff)
            .values(status="failed")
        )
        total = (dead.rowcount or 0) + (requeued.rowcount or 0)
        if total:
            logger.warning("Recovered %d stuck job(s)", total)
        return total


async def purge_old_jobs() -> int:
    """Retention: drop finished jobs so the table (and its idempotency keys)
    doesn't grow forever. Keys must outlive any realistic provider-retry or
    dedup window — the defaults keep them for weeks."""
    settings = get_settings()
    removed = 0
    async with db_session() as db:
        if settings.retention_done_jobs_days > 0:
            cutoff = utcnow() - timedelta(days=settings.retention_done_jobs_days)
            res = await db.execute(
                delete(Job).where(Job.status == "done", Job.updated_at < cutoff)
            )
            removed += res.rowcount or 0
        if settings.retention_dead_jobs_days > 0:
            cutoff = utcnow() - timedelta(days=settings.retention_dead_jobs_days)
            res = await db.execute(
                delete(Job).where(Job.status == "dead", Job.updated_at < cutoff)
            )
            removed += res.rowcount or 0
    return removed

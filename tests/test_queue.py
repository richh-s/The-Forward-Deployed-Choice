"""Job queue: execution, retry with backoff, idempotency, dead-lettering."""
from sqlalchemy import select

from engine.db import db_session
from engine.models import Job
from engine.queue import enqueue, job_handler, process_one


@job_handler("test_ok")
async def _ok(db, job):
    job.payload["ran"] = True


_fail_count = {"n": 0}


@job_handler("test_flaky")
async def _flaky(db, job):
    _fail_count["n"] += 1
    raise RuntimeError("boom")


async def test_process_success():
    async with db_session() as db:
        job = await enqueue(db, "test_ok", {"x": 1})
        job_id = job.id
    assert await process_one() is True
    async with db_session() as db:
        job = await db.get(Job, job_id)
        assert job.status == "done"


async def test_empty_queue_returns_false():
    assert await process_one() is False


async def test_idempotency_key_dedups():
    async with db_session() as db:
        first = await enqueue(db, "test_ok", {}, idempotency_key="same")
        assert first is not None
    async with db_session() as db:
        dup = await enqueue(db, "test_ok", {}, idempotency_key="same")
        assert dup is None


async def test_retry_then_dead():
    _fail_count["n"] = 0
    async with db_session() as db:
        job = await enqueue(db, "test_flaky", {}, max_attempts=2)
        job_id = job.id
    assert await process_one() is True
    async with db_session() as db:
        job = await db.get(Job, job_id)
        assert job.status == "failed" and job.attempts == 1
        assert "boom" in job.last_error
        job.run_after = job.created_at  # make it due again immediately
    assert await process_one() is True
    async with db_session() as db:
        job = await db.get(Job, job_id)
        assert job.status == "dead" and job.attempts == 2
    # Dead jobs never run again.
    assert await process_one() is False
    assert _fail_count["n"] == 2


async def test_unknown_job_type_fails_safely():
    async with db_session() as db:
        job = await enqueue(db, "no_such_handler", {}, max_attempts=1)
        job_id = job.id
    await process_one()
    async with db_session() as db:
        job = await db.get(Job, job_id)
        assert job.status == "dead"
        assert "No handler" in job.last_error


async def test_duplicate_enqueue_preserves_caller_transaction():
    """A duplicate idempotency key must roll back only its SAVEPOINT — never
    the caller's other writes (regression: sent emails were losing their
    Message/state records on the 2nd+ touch)."""
    from tests.conftest import seed_workspace

    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "test_ok", {}, idempotency_key="dup-key")
    async with db_session() as db:
        from engine.models import Suppression

        # Work done before the duplicate enqueue...
        db.add(Suppression(
            workspace_id=seed["workspace_id"], channel="email",
            address="keepme@x.test", reason="manual",
        ))
        await db.flush()
        dup = await enqueue(db, "test_ok", {}, idempotency_key="dup-key")
        assert dup is None
    async with db_session() as db:
        from engine.models import Suppression

        rows = (await db.execute(
            select(Suppression).where(Suppression.address == "keepme@x.test")
        )).scalars().all()
        assert rows, "duplicate enqueue rolled back the caller's writes"


async def test_recover_stuck_jobs_respects_attempt_budget():
    from datetime import timedelta

    from engine.models import utcnow
    from engine.queue import recover_stuck_jobs

    async with db_session() as db:
        fresh = await enqueue(db, "test_ok", {}, max_attempts=3)
        spent = await enqueue(db, "test_ok", {}, max_attempts=1)
        stale = utcnow() - timedelta(hours=1)
        for j, attempts in ((fresh, 1), (spent, 1)):
            j.status = "running"
            j.attempts = attempts
        fresh_id, spent_id = fresh.id, spent.id
    async with db_session() as db:
        from sqlalchemy import update

        await db.execute(update(Job).values(updated_at=stale))
    await recover_stuck_jobs(older_than_minutes=15)
    async with db_session() as db:
        assert (await db.get(Job, fresh_id)).status == "failed"   # retryable
        assert (await db.get(Job, spent_id)).status == "dead"     # budget spent


async def test_jobs_run_oldest_first():
    async with db_session() as db:
        await enqueue(db, "test_ok", {"o": 1})
        await enqueue(db, "test_ok", {"o": 2})
    await process_one()
    await process_one()
    async with db_session() as db:
        jobs = (await db.execute(select(Job).order_by(Job.created_at))).scalars().all()
        assert all(j.status == "done" for j in jobs)

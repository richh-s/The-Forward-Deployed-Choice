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


async def test_jobs_run_oldest_first():
    async with db_session() as db:
        await enqueue(db, "test_ok", {"o": 1})
        await enqueue(db, "test_ok", {"o": 2})
    await process_one()
    await process_one()
    async with db_session() as db:
        jobs = (await db.execute(select(Job).order_by(Job.created_at))).scalars().all()
        assert all(j.status == "done" for j in jobs)

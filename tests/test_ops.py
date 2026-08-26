"""Operational endpoints: health, metrics, jobs dashboard, PII deletion."""
import httpx
from sqlalchemy import select

from engine.db import db_session
from engine.models import Message, Prospect, Suppression
from tests.conftest import login, post, seed_workspace


async def test_health_reports_database(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["database"] == "ok"
    # RUN_WORKER=false in tests — no worker/scheduler checks expected.
    assert "worker" not in body["checks"]


async def test_health_live(client: httpx.AsyncClient):
    resp = await client.get("/health/live")
    assert resp.status_code == 200


async def test_metrics_endpoint(client: httpx.AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "engine_workspaces_paused" in resp.text


async def test_jobs_page_lists_dead_jobs(client: httpx.AsyncClient):
    from engine.queue import enqueue

    seed = await seed_workspace()
    async with db_session() as db:
        job = await enqueue(
            db, "test_dead", {}, workspace_id=seed["workspace_id"]
        )
        job.status = "dead"
        job.last_error = "handler exploded"
        job_id = job.id
    await login(client, seed["email"])
    page = await client.get("/jobs")
    assert page.status_code == 200 and "handler exploded" in page.text
    # Admin can requeue it.
    resp = await post(client, f"/jobs/{job_id}/retry")
    assert resp.status_code == 303
    async with db_session() as db:
        from engine.models import Job

        job = await db.get(Job, job_id)
        assert job.status == "failed" and job.attempts == 0


async def test_prospect_deletion_erases_pii_keeps_suppression(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    async with db_session() as db:
        db.add(Message(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            channel="email", direction="out", body="hello",
        ))
    await login(client, seed["email"])
    resp = await post(client, f"/prospects/{seed['prospect_id']}/delete")
    assert resp.status_code == 303
    async with db_session() as db:
        assert await db.get(Prospect, seed["prospect_id"]) is None
        messages = (await db.execute(
            select(Message).where(Message.prospect_id == seed["prospect_id"])
        )).scalars().all()
        assert not messages
        # The address stays on the do-not-contact list.
        suppressed = (await db.execute(
            select(Suppression).where(
                Suppression.address == seed["prospect_email"]
            )
        )).scalars().all()
        assert suppressed

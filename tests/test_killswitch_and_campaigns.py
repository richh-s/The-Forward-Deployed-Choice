"""Kill-switch auto-pause, campaign CSV import, and scheduler gating."""
import io
from datetime import timedelta

import httpx
from sqlalchemy import select

from engine.db import db_session
from engine.models import Campaign, Job, Message, Prospect, Suppression, Workspace, utcnow
from engine.services.killswitch import compute_metrics, evaluate_killswitch
from engine.services.scheduler import run_scheduler_pass
from tests.conftest import login, seed_workspace


async def _add_outbound(db, ws_id, n, status="sent"):
    for i in range(n):
        db.add(Message(
            workspace_id=ws_id, channel="email", direction="out",
            body=f"m{i}", status=status,
        ))


async def test_killswitch_pauses_on_optout_rate():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        await _add_outbound(db, ws.id, 30)
        for i in range(5):  # 5/30 ≈ 17% opt-out — over the 5% default
            db.add(Suppression(
                workspace_id=ws.id, channel="email",
                address=f"p{i}@x.test", reason="opt_out",
            ))
        await db.flush()
        breaches = await evaluate_killswitch(db, ws)
        assert breaches and ws.outbound_paused
        assert "opt_out_rate" in ws.pause_reason


async def test_killswitch_ignores_tiny_samples():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        await _add_outbound(db, ws.id, 2)
        db.add(Suppression(
            workspace_id=ws.id, channel="email", address="p@x.test",
            reason="opt_out",
        ))
        await db.flush()
        breaches = await evaluate_killswitch(db, ws)
        assert not breaches and not ws.outbound_paused


async def test_metrics_shape():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        metrics = await compute_metrics(db, ws)
    assert {"emails_out", "opt_out_rate", "bounce_rate", "llm_cost_usd",
            "cost_per_qualified_lead", "qualified_leads"} <= metrics.keys()


async def test_csv_import(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    csv_content = (
        "email,name,company,phone,signals\n"
        'new1@x.test,Ann A,Aco,+254711111111,"{""signal_1"": {""confidence"": ""high""}}"\n'
        "new2@x.test,Bob B,Bco,,\n"
        "not-an-email,Bad,Bad,,\n"
        f"{seed['prospect_email']},Dup,Dup,,\n"
    )
    resp = await client.post(
        f"/campaigns/{seed['campaign_id']}/upload",
        files={"file": ("prospects.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert "Imported+2" in loc and "1+duplicates" in loc and "1+invalid" in loc
    async with db_session() as db:
        prospects = (await db.execute(
            select(Prospect).where(Prospect.workspace_id == seed["workspace_id"])
        )).scalars().all()
        assert len(prospects) == 3  # seed prospect + 2 imported
        ann = next(p for p in prospects if p.email == "new1@x.test")
        assert ann.stage == "enriched" and ann.phone == "+254711111111"
        bob = next(p for p in prospects if p.email == "new2@x.test")
        assert bob.stage == "new"


async def test_scheduler_enqueues_first_touches_within_cap():
    seed = await seed_workspace()
    async with db_session() as db:
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.daily_cap = 1
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 24
        db.add(Prospect(
            workspace_id=seed["workspace_id"], campaign_id=campaign.id,
            email="second@x.test", stage="new",
        ))
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert len(jobs) == 1  # cap respected
    # A second pass must not enqueue a duplicate for the same prospect.
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert len(jobs) == 2  # first prospect (claimed) + second prospect
        keys = {j.idempotency_key for j in jobs}
        assert len(keys) == 2


async def test_scheduler_respects_send_window():
    seed = await seed_workspace()
    async with db_session() as db:
        campaign = await db.get(Campaign, seed["campaign_id"])
        # An empty window can never match.
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 0
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert not jobs


async def test_followup_enqueued_when_due():
    seed = await seed_workspace()
    async with db_session() as db:
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.sequence = [{"day_offset": 3, "angle": "case study"}]
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 24
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.stage = "contacted"
        prospect.touch_count = 1
        prospect.next_followup_at = utcnow() - timedelta(hours=1)
    await run_scheduler_pass()
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalar_one()
        assert job.payload["touch_number"] == 2
        assert job.payload["angle"] == "case study"

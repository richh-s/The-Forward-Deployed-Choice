"""Feature-gap hardening: reply approval gate, kill-switch draft spend,
follow-up send windows, permanent LLM failures, enrichment wiring, bulk
approve clamping, test sends, and account recovery."""
import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select, update

from engine.db import db_session
from engine.models import (
    AuthSession,
    Campaign,
    Draft,
    Job,
    Prospect,
    User,
    Workspace,
    utcnow,
)
from engine.queue import enqueue, process_one
from engine.services.credentials import set_credentials
from engine.services.killswitch import evaluate_killswitch
from engine.services.llm import LLMPermanentError, LLMResult
from engine.services.scheduler import run_scheduler_pass
from tests.conftest import login, post, seed_workspace

WARM_REPLY = {
    "intent": "warm",
    "reply": "Great to hear! Here's our booking link.",
    "escalate": False,
    "escalation_reason": "",
}


def _llm(payload: dict) -> LLMResult:
    return LLMResult(
        text=json.dumps(payload), model="claude-opus-5",
        input_tokens=500, output_tokens=200,
    )


async def _seed_with_resend() -> dict:
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend", {"api_key": "re_test"}
        )
    return seed


async def _enqueue_inbound(seed, text="Sounds interesting!"):
    async with db_session() as db:
        await enqueue(db, "inbound_message", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
            "channel": "email",
            "text": text,
        })


# ── reply approval gate ───────────────────────────────────────────────


async def test_reply_is_held_for_approval_by_default():
    seed = await _seed_with_resend()
    sent = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        sent.append(payload)
        return {"id": "re_x"}

    with patch(
        "engine.services.llm.complete",
        new=AsyncMock(return_value=_llm(WARM_REPLY)),
    ), patch(
        "engine.services.emailer._resend_send",
        new=AsyncMock(side_effect=fake_resend),
    ):
        await _enqueue_inbound(seed)
        while await process_one():
            pass

    assert not sent  # nothing reached the provider
    async with db_session() as db:
        draft = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalar_one()
        assert draft.status == "pending_review"
        assert draft.judge_score is None
        assert draft.compose_cost_usd > 0  # reply-agent cost recorded


async def test_approving_held_reply_sends_it(client: httpx.AsyncClient):
    seed = await _seed_with_resend()
    with patch(
        "engine.services.llm.complete",
        new=AsyncMock(return_value=_llm(WARM_REPLY)),
    ):
        await _enqueue_inbound(seed)
        assert await process_one()

    await login(client, seed["email"])
    async with db_session() as db:
        draft_id = (await db.execute(select(Draft))).scalar_one().id
    resp = await post(
        client, f"/approvals/{draft_id}/approve",
        data={"subject": "Re: your reply", "body": "Edited reply body."},
    )
    assert resp.status_code == 303

    sent = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        sent.append(payload)
        return {"id": "re_y"}

    with patch(
        "engine.services.emailer._resend_send",
        new=AsyncMock(side_effect=fake_resend),
    ):
        while await process_one():
            pass
    assert len(sent) == 1 and "Edited reply body." in sent[0]["text"]
    async with db_session() as db:
        draft = await db.get(Draft, draft_id)
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert draft.status == "sent"
        # A reply is not an outreach touch — sequence state untouched.
        assert prospect.touch_count == 0
        assert prospect.next_followup_at is None


async def test_escalated_reply_is_held_even_with_auto_send():
    seed = await _seed_with_resend()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.require_reply_approval = False
    escalated = {
        "intent": "question",
        "reply": "Our enterprise pricing starts at...",
        "escalate": True,
        "escalation_reason": "pricing beyond public bands",
    }
    with patch(
        "engine.services.llm.complete",
        new=AsyncMock(return_value=_llm(escalated)),
    ):
        await _enqueue_inbound(seed, "What's your enterprise price?")
        while await process_one():
            pass
    async with db_session() as db:
        draft = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalar_one()
        assert draft.status == "pending_review"


# ── kill-switch sees unsent draft spend ──────────────────────────────


async def test_killswitch_counts_llm_spend_on_unsent_drafts():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.killswitch = {"max_llm_cost_usd": 5.0}
        # A compose→reject loop: real spend, zero sends, zero messages.
        for i in range(3):
            db.add(Draft(
                workspace_id=ws.id,
                prospect_id=seed["prospect_id"],
                body=f"draft {i}",
                status="rejected",
                compose_cost_usd=2.5,
            ))
        await db.flush()
        breaches = await evaluate_killswitch(db, ws)
        assert breaches and ws.outbound_paused
        assert "llm_cost_usd" in ws.pause_reason


# ── follow-up scheduling fixes ───────────────────────────────────────


async def test_followups_respect_send_window():
    seed = await seed_workspace()
    async with db_session() as db:
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.sequence = [{"day_offset": 3, "angle": "case study"}]
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 0  # empty window: never in-window
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.stage = "contacted"
        prospect.touch_count = 1
        prospect.next_followup_at = utcnow() - timedelta(hours=1)
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert not jobs
        # The due follow-up is preserved for the next in-window pass.
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.next_followup_at is not None


async def test_followup_with_no_sends_is_cleared_not_missequenced():
    seed = await seed_workspace()
    async with db_session() as db:
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.sequence = [
            {"day_offset": 3, "angle": "first"},
            {"day_offset": 7, "angle": "last"},
        ]
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 24
        prospect = await db.get(Prospect, seed["prospect_id"])
        # Operator moved the prospect to contacted manually; nothing sent.
        prospect.stage = "contacted"
        prospect.touch_count = 0
        prospect.next_followup_at = utcnow() - timedelta(hours=1)
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert not jobs  # steps[-1] would have silently picked "last"
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.next_followup_at is None


# ── permanent LLM failures dead-letter immediately ───────────────────


async def test_llm_refusal_goes_straight_to_dead():
    seed = await seed_workspace()
    with patch(
        "engine.services.llm.complete",
        new=AsyncMock(side_effect=LLMPermanentError("Model declined the request")),
    ):
        async with db_session() as db:
            job = await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
            job_id = job.id
        assert await process_one()
    async with db_session() as db:
        job = await db.get(Job, job_id)
        assert job.status == "dead"
        assert job.attempts == 1  # no billable identical retries
        assert "declined" in job.last_error


# ── enrichment wiring ────────────────────────────────────────────────


async def test_scheduler_enriches_new_prospects_when_source_configured():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "enrichment",
            {"url": "https://signals.example.com/enrich", "api_key": "k"},
        )
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.send_window_start_hour = 0
        campaign.send_window_end_hour = 24
        db.add(Prospect(
            workspace_id=seed["workspace_id"], campaign_id=campaign.id,
            email="fresh@x.test", stage="new", company="Fresh Co",
        ))
    await run_scheduler_pass()
    async with db_session() as db:
        enrich_jobs = (await db.execute(
            select(Job).where(Job.type == "enrich_prospect")
        )).scalars().all()
        assert len(enrich_jobs) == 1  # only the 'new' prospect
        # The 'new' prospect is NOT composed until enriched.
        compose_targets = {
            j.payload["prospect_id"] for j in (await db.execute(
                select(Job).where(Job.type == "compose_draft")
            )).scalars().all()
        }
        fresh = (await db.execute(
            select(Prospect).where(Prospect.email == "fresh@x.test")
        )).scalar_one()
        assert fresh.id not in compose_targets

    signals = {"signal_1_funding_event": {"confidence": "high"}}
    with patch(
        "engine.services.enrichment.fetch_signals",
        new=AsyncMock(return_value=signals),
    ):
        while await process_one():
            pass
    async with db_session() as db:
        fresh = (await db.execute(
            select(Prospect).where(Prospect.email == "fresh@x.test")
        )).scalar_one()
        assert fresh.stage == "enriched"
        assert fresh.signals == signals


async def test_enrichment_failure_eventually_proceeds_unenriched():
    seed = await seed_workspace(with_campaign=True)
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "enrichment",
            {"url": "https://signals.example.com/enrich"},
        )
        db.add(Prospect(
            workspace_id=seed["workspace_id"],
            campaign_id=seed["campaign_id"],
            email="unlucky@x.test", stage="new",
        ))
        await db.flush()
        prospect_id = (await db.execute(
            select(Prospect.id).where(Prospect.email == "unlucky@x.test")
        )).scalar_one()
        await enqueue(db, "enrich_prospect", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": prospect_id,
        }, max_attempts=1)  # final attempt immediately
    with patch(
        "engine.services.enrichment.fetch_signals",
        new=AsyncMock(side_effect=httpx.ConnectError("down")),
    ):
        assert await process_one()
    async with db_session() as db:
        prospect = await db.get(Prospect, prospect_id)
        assert prospect.stage == "enriched"  # proceeds without signals
        # The failure leaves a visible marker for the operator (and the
        # composer ignores non-dict values, so it still runs inquiry mode).
        assert prospect.signals == {"_enrichment_failed": True}


# ── approvals: clamping and test sends ───────────────────────────────


async def test_bulk_approve_clamps_min_score_and_skips_replies(
    client: httpx.AsyncClient,
):
    seed = await _seed_with_resend()
    async with db_session() as db:
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            body="outreach", judge_score=0.95, status="pending_review",
        ))
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            body="a reply", kind="reply", status="pending_review",
        ))
    await login(client, seed["email"])
    # Nonsense threshold clamps to 1.0 — the 0.95 draft is NOT approved.
    resp = await post(client, "/approvals/bulk-approve", data={"min_score": "5"})
    assert resp.status_code == 303
    async with db_session() as db:
        drafts = (await db.execute(select(Draft))).scalars().all()
        assert all(d.status == "pending_review" for d in drafts)
    # A sane threshold approves the judged outreach draft but never the
    # unjudged reply.
    await post(client, "/approvals/bulk-approve", data={"min_score": "0.9"})
    async with db_session() as db:
        outreach = (await db.execute(
            select(Draft).where(Draft.kind == "outreach")
        )).scalar_one()
        reply = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalar_one()
        assert outreach.status == "approved"
        assert reply.status == "pending_review"


async def test_test_send_goes_to_reviewer_not_prospect(client: httpx.AsyncClient):
    seed = await _seed_with_resend()
    async with db_session() as db:
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            subject="Hello", body="Draft body", status="pending_review",
        ))
        await db.flush()
        draft_id = (await db.execute(select(Draft.id))).scalar_one()
    await login(client, seed["email"])
    sent = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        sent.append(payload)
        return {"id": "re_t"}

    with patch(
        "engine.services.emailer._resend_send",
        new=AsyncMock(side_effect=fake_resend),
    ):
        resp = await post(client, f"/approvals/{draft_id}/test-send")
    assert resp.status_code == 303
    assert len(sent) == 1
    assert sent[0]["to"] == [seed["email"]]
    assert sent[0]["subject"].startswith("[TEST]")
    async with db_session() as db:
        draft = await db.get(Draft, draft_id)
        assert draft.status == "pending_review"  # untouched


async def test_compose_now_enqueues_manual_draft(client: httpx.AsyncClient):
    seed = await _seed_with_resend()
    await login(client, seed["email"])
    resp = await post(client, f"/prospects/{seed['prospect_id']}/compose")
    assert resp.status_code == 303
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalar_one()
        assert job.payload["prospect_id"] == seed["prospect_id"]
        assert job.payload["manual"] is True


# ── account recovery & sessions ──────────────────────────────────────


async def test_admin_created_user_must_change_password(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await post(client, "/settings/users", data={
        "email": "newbie@acme.test", "name": "New B",
        "password": "temporary-pass-1", "role": "operator",
    })
    assert resp.status_code == 303

    fresh = httpx.AsyncClient(
        transport=client._transport, base_url="http://testserver"
    )
    async with fresh:
        await login(fresh, "newbie@acme.test", "temporary-pass-1")
        blocked = await fresh.get("/prospects")
        assert blocked.status_code == 303
        assert blocked.headers["location"].startswith("/settings")
        # The settings page (with the change form) is reachable.
        allowed = await fresh.get("/settings")
        assert allowed.status_code == 200
        # Changing the password lifts the restriction.
        resp = await post(fresh, "/settings/password", data={
            "current_password": "temporary-pass-1",
            "new_password": "my-own-password-1",
        })
        assert resp.status_code == 303
        await login(fresh, "newbie@acme.test", "my-own-password-1")
        assert (await fresh.get("/prospects")).status_code == 200


async def test_admin_password_reset_revokes_sessions(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        from engine.security import hash_password

        db.add(User(
            workspace_id=seed["workspace_id"], email="op@acme.test",
            password_hash=hash_password("operator-pass-1"), role="operator",
        ))
        await db.flush()
        op_id = (await db.execute(
            select(User.id).where(User.email == "op@acme.test")
        )).scalar_one()

    op_client = httpx.AsyncClient(
        transport=client._transport, base_url="http://testserver"
    )
    async with op_client:
        await login(op_client, "op@acme.test", "operator-pass-1")
        assert (await op_client.get("/")).status_code == 200

        await login(client, seed["email"])
        resp = await post(client, f"/settings/users/{op_id}/reset-password")
        assert resp.status_code == 200
        assert "Temporary password" in resp.text

        # The operator's session is gone.
        assert (await op_client.get("/")).status_code != 200


async def test_sessions_have_absolute_lifetime(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    assert (await client.get("/")).status_code == 200
    async with db_session() as db:
        # Simulate a cookie kept alive by sliding renewal for 40 days.
        await db.execute(update(AuthSession).values(
            created_at=utcnow() - timedelta(days=40),
            expires_at=utcnow() + timedelta(days=1),
        ))
    assert (await client.get("/")).status_code != 200


# ── dead-job visibility ──────────────────────────────────────────────


async def test_dead_jobs_banner_on_dashboard(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "no_such_handler", {},
                      workspace_id=seed["workspace_id"], max_attempts=1)
    await process_one()  # dead-letters it
    await login(client, seed["email"])
    page = await client.get("/")
    assert "permanently failed" in page.text


# ── settings: Africa's Talking webhook URL ───────────────────────────


async def test_at_webhook_url_visible_to_admin(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "africastalking",
            {"username": "sandbox", "api_key": "atk",
             "webhook_token": "tok-1234567890abcdef"},
        )
    await login(client, seed["email"])
    page = await client.get("/settings")
    assert "tok-1234567890abcdef" in page.text

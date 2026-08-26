"""End-to-end pipeline with the LLM and providers mocked at the seams:
compose → judge → approval queue → send (sink mode) → inbound reply →
reply agent → booking webhook closes the loop."""
import json
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select

from engine.db import db_session
from engine.models import Booking, Draft, Job, Message, Prospect
from engine.queue import enqueue, process_one
from engine.services.credentials import set_credentials
from engine.services.llm import LLMResult
from tests.conftest import login, post, seed_workspace

COMPOSE_JSON = {
    "subject": "Question about Prospect Co's hiring plans",
    "body": "Hi Jane,\n\nCongrats on the recent raise. Are you planning to grow "
    "the engineering team this quarter?\n\nAlex, Engagement Manager",
    "mode_used": "assertion",
    "grounding_notes": "funding event: high confidence",
}
JUDGE_GOOD = {
    "signal_grounding": 1.0, "mode_compliance": 1.0, "tone": 0.9,
    "structure": 1.0, "hallucination_free": 1.0, "feedback": "Clean draft.",
}


def _llm_result(payload: dict) -> LLMResult:
    return LLMResult(
        text=json.dumps(payload), model="claude-opus-5",
        input_tokens=500, output_tokens=200,
    )


def mock_llm(responses):
    """Patch llm.complete to return canned results in order (cycling last)."""
    queue = list(responses)

    async def fake_complete(db, workspace_id, **kwargs):
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return _llm_result(payload)

    return patch(
        "engine.services.llm.complete", new=AsyncMock(side_effect=fake_complete)
    )


async def _seed_with_resend(require_approval=True):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend", {"api_key": "re_test"}
        )
        from engine.models import Campaign

        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.require_approval = require_approval
        campaign.auto_approve_score = 0.8
    return seed


async def test_compose_creates_pending_draft():
    seed = await _seed_with_resend()
    with mock_llm([COMPOSE_JSON, JUDGE_GOOD]):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
        assert await process_one()
    async with db_session() as db:
        draft = (await db.execute(select(Draft))).scalar_one()
        assert draft.status == "pending_review"
        assert draft.judge_score is not None and draft.judge_score > 0.9
        assert draft.compose_cost_usd > 0
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "queued"


async def test_low_judge_score_triggers_regeneration():
    seed = await _seed_with_resend()
    judge_bad = {**JUDGE_GOOD, "hallucination_free": 0.0, "feedback": "Invented a number."}
    calls = []

    responses = [COMPOSE_JSON, judge_bad, COMPOSE_JSON, JUDGE_GOOD]

    async def fake_complete(db, workspace_id, **kwargs):
        calls.append(kwargs.get("system", "")[:20])
        return _llm_result(responses[len(calls) - 1])

    with patch("engine.services.llm.complete", new=AsyncMock(side_effect=fake_complete)):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
        assert await process_one()
    assert len(calls) == 4  # compose, judge, re-compose, re-judge
    async with db_session() as db:
        draft = (await db.execute(select(Draft))).scalar_one()
        assert draft.judge_score > 0.9


async def test_auto_approve_sends_via_sink(client: httpx.AsyncClient):
    seed = await _seed_with_resend(require_approval=False)
    resend_calls = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        resend_calls.append(payload)
        return {"id": "re_msg_1"}

    with mock_llm([COMPOSE_JSON, JUDGE_GOOD]), patch(
        "engine.services.emailer._resend_send", new=AsyncMock(side_effect=fake_resend)
    ):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
        assert await process_one()  # compose (enqueues send)
        assert await process_one()  # send

    assert len(resend_calls) == 1
    payload = resend_calls[0]
    # Sink mode: the real prospect is NOT the recipient.
    assert payload["to"] == ["sink@example.com"]
    assert payload["headers"]["X-Intended-Recipient"] == seed["prospect_email"]
    assert "unsubscribe" in payload["text"].lower()
    assert "List-Unsubscribe" in payload["headers"]

    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "contacted" and prospect.touch_count == 1
        message = (await db.execute(
            select(Message).where(Message.direction == "out")
        )).scalar_one()
        assert message.provider_message_id == "re_msg_1"
        # LLM cost lives on the Draft (counted even if never sent); the sent
        # Message no longer duplicates it.
        assert message.cost_usd == 0
        draft = (await db.execute(select(Draft))).scalar_one()
        assert draft.compose_cost_usd > 0


async def test_manual_approval_flow(client: httpx.AsyncClient):
    seed = await _seed_with_resend(require_approval=True)
    with mock_llm([COMPOSE_JSON, JUDGE_GOOD]):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
        assert await process_one()

    await login(client, seed["email"])
    page = await client.get("/approvals")
    assert "Jane Doe" in page.text

    async with db_session() as db:
        draft = (await db.execute(select(Draft))).scalar_one()
        draft_id = draft.id
    resp = await post(
        client, f"/approvals/{draft_id}/approve",
        data={"subject": "Edited subject", "body": "Edited body from a human."},
    )
    assert resp.status_code == 303

    async def fake_resend(api_key, payload, idempotency_key=None):
        assert payload["subject"] == "Edited subject"
        return {"id": "re_msg_2"}

    with patch(
        "engine.services.emailer._resend_send", new=AsyncMock(side_effect=fake_resend)
    ):
        assert await process_one()  # the send job
    async with db_session() as db:
        draft = await db.get(Draft, draft_id)
        assert draft.status == "sent" and draft.reviewed_by == seed["user_id"]


async def test_reject_prevents_send(client: httpx.AsyncClient):
    seed = await _seed_with_resend()
    with mock_llm([COMPOSE_JSON, JUDGE_GOOD]):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
            })
        assert await process_one()
    await login(client, seed["email"])
    async with db_session() as db:
        draft_id = (await db.execute(select(Draft))).scalar_one().id
    await post(client, f"/approvals/{draft_id}/reject", data={"reason": "off-brand"})
    async with db_session() as db:
        draft = await db.get(Draft, draft_id)
        assert draft.status == "rejected"
        jobs = (await db.execute(
            select(Job).where(Job.type == "send_draft")
        )).scalars().all()
        assert not jobs


async def test_cold_reply_suppresses_prospect():
    seed = await _seed_with_resend()
    cold = {"intent": "cold", "reply": "", "escalate": False, "escalation_reason": ""}
    with mock_llm([cold]):
        async with db_session() as db:
            await enqueue(db, "inbound_message", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "channel": "email",
                "text": "Please remove me from your list.",
            })
        assert await process_one()
    async with db_session() as db:
        from engine.services.suppression import is_suppressed

        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "opted_out"
        assert await is_suppressed(
            db, seed["workspace_id"], "email", seed["prospect_email"]
        )


async def test_warm_reply_sends_agent_response_when_auto_send_enabled():
    seed = await _seed_with_resend()
    async with db_session() as db:
        from engine.models import Workspace

        ws = await db.get(Workspace, seed["workspace_id"])
        ws.require_reply_approval = False  # workspace opted into auto-send
    warm = {
        "intent": "warm",
        "reply": "Great to hear! Here's our booking link.",
        "escalate": False,
        "escalation_reason": "",
    }
    sent = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        sent.append(payload)
        return {"id": "re_msg_3"}

    with mock_llm([warm]), patch(
        "engine.services.emailer._resend_send", new=AsyncMock(side_effect=fake_resend)
    ):
        async with db_session() as db:
            await enqueue(db, "inbound_message", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "channel": "email",
                "text": "Sounds interesting — let's talk!",
            })
        # inbound_message creates the auto-approved reply draft, then the
        # queued send_draft job delivers it.
        while await process_one():
            pass
    assert len(sent) == 1
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "warm"
        draft = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalar_one()
        assert draft.status == "sent" and draft.auto_approved


async def test_second_touch_send_is_fully_recorded():
    """Regression: the 2nd touch's HubSpot enqueue used to collide on a
    per-prospect idempotency key and roll back the whole send record."""
    seed = await _seed_with_resend(require_approval=False)

    async def fake_resend(api_key, payload, idempotency_key=None):
        return {"id": f"re_{len(sent) + 1}"}

    sent = []
    for touch in (1, 2):
        async with db_session() as db:
            draft = Draft(
                workspace_id=seed["workspace_id"],
                prospect_id=seed["prospect_id"],
                campaign_id=seed["campaign_id"],
                subject=f"Touch {touch}",
                body="Body",
                status="approved",
                touch_number=touch,
            )
            db.add(draft)
            await db.flush()
            await enqueue(db, "send_draft", {"draft_id": draft.id},
                          idempotency_key=f"send_draft:{draft.id}")
        with patch(
            "engine.services.emailer._resend_send",
            new=AsyncMock(side_effect=fake_resend),
        ):
            # Drain everything (the send plus the HubSpot sync it enqueues).
            while await process_one():
                pass
        sent.append(touch)

    async with db_session() as db:
        messages = (await db.execute(
            select(Message).where(Message.direction == "out")
        )).scalars().all()
        assert len(messages) == 2  # both sends recorded
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.touch_count == 2
        drafts = (await db.execute(select(Draft))).scalars().all()
        assert all(d.status == "sent" for d in drafts)
        hs_jobs = (await db.execute(
            select(Job).where(Job.type == "sync_hubspot_contact")
        )).scalars().all()
        assert len(hs_jobs) == 2  # one per touch — key is per-draft now


async def test_booking_metadata_cannot_reach_other_workspace():
    """Cal.com metadata is attacker-controllable — a prospect_id from
    another workspace must be ignored."""
    from engine.models import Workspace
    from engine.services.booking import record_booking_event

    seed_a = await seed_workspace(slug="alpha", admin_email="a@alpha.test")
    seed_b = await seed_workspace(slug="beta", admin_email="b@beta.test")
    async with db_session() as db:
        ws_a = await db.get(Workspace, seed_a["workspace_id"])
        booking = await record_booking_event(
            db, ws_a, "BOOKING_CREATED",
            {
                "uid": "bk_evil",
                "startTime": "2026-09-01T14:00:00Z",
                "metadata": {"prospect_id": seed_b["prospect_id"]},
                "attendees": [],
            },
        )
        assert booking is not None and booking.prospect_id is None
    async with db_session() as db:
        victim = await db.get(Prospect, seed_b["prospect_id"])
        assert victim.stage != "booked"  # untouched


async def test_booking_webhook_closes_loop(client: httpx.AsyncClient):
    import hashlib
    import hmac as hmac_mod

    seed = await _seed_with_resend()
    secret = "cal-secret"
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "calcom",
            {"api_key": "k", "webhook_secret": secret},
        )
    payload = json.dumps({
        "triggerEvent": "BOOKING_CREATED",
        "payload": {
            "uid": "bk_123",
            "startTime": "2026-09-01T14:00:00Z",
            "metadata": {"prospect_id": seed["prospect_id"]},
            "attendees": [{"email": seed["prospect_email"]}],
        },
    }).encode()
    sig = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/webhooks/acme/calcom", content=payload,
        headers={"x-cal-signature-256": sig},
    )
    assert resp.status_code == 200
    async with db_session() as db:
        booking = (await db.execute(select(Booking))).scalar_one()
        assert booking.provider_uid == "bk_123"
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "booked"
        hs_jobs = (await db.execute(
            select(Job).where(Job.type == "hubspot_mark_booked")
        )).scalars().all()
        assert len(hs_jobs) == 1

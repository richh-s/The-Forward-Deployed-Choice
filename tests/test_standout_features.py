"""Differentiator features: learning loop, evidence-linked approvals, edit
tracking + judge export, Slack notifications, deliverability warm-up,
WhatsApp channel, booking reminders, and the weekly digest."""
import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select

from engine.db import db_session
from engine.models import Booking, Campaign, Draft, Job, Message, Prospect, Workspace, utcnow
from engine.queue import enqueue, process_one
from engine.services import learning
from engine.services.credentials import set_credentials
from engine.services.llm import LLMResult
from engine.services.scheduler import run_scheduler_pass
from tests.conftest import login, post, seed_workspace

COMPOSE_JSON = {
    "subject": "Congrats on the raise",
    "body": "Hi Jane,\n\nCongrats on the recent funding.\n\nAlex",
    "mode_used": "assertion",
    "grounding_notes": "funding claim ← signal_1_funding_event (high)",
}
JUDGE_GOOD = {
    "signal_grounding": 1.0, "mode_compliance": 0.9, "tone": 0.9,
    "structure": 1.0, "hallucination_free": 1.0, "feedback": "Clean.",
}


def _llm(payload):
    return LLMResult(text=json.dumps(payload), model="claude-opus-5",
                     input_tokens=400, output_tokens=150)


def mock_llm(responses):
    queue = list(responses)

    async def fake(db, workspace_id, **kwargs):
        return _llm(queue.pop(0) if len(queue) > 1 else queue[0])

    return patch("engine.services.llm.complete", new=AsyncMock(side_effect=fake))


# ── evidence-linked approvals ────────────────────────────────────────


async def test_compose_stores_evidence_and_angle():
    seed = await seed_workspace()
    with mock_llm([COMPOSE_JSON, JUDGE_GOOD]):
        async with db_session() as db:
            await enqueue(db, "compose_draft", {
                "workspace_id": seed["workspace_id"],
                "prospect_id": seed["prospect_id"],
                "campaign_id": seed["campaign_id"],
                "angle": "post-funding growth",
            })
        assert await process_one()
    async with db_session() as db:
        draft = (await db.execute(select(Draft))).scalar_one()
        assert draft.angle == "post-funding growth"
        assert "signal_1_funding_event" in draft.grounding_notes
        assert draft.judge_scores["hallucination_free"] == 1.0
        assert set(draft.judge_scores) == {
            "signal_grounding", "mode_compliance", "tone", "structure",
            "hallucination_free",
        }


# ── edit tracking + judge export ─────────────────────────────────────


async def test_edit_ratio_recorded_and_exported(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            subject="Original subject", body="Original body text here.",
            judge_score=0.92, status="pending_review",
        ))
    await login(client, seed["email"])
    async with db_session() as db:
        draft_id = (await db.execute(select(Draft.id))).scalar_one()
    await post(client, f"/approvals/{draft_id}/approve", data={
        "subject": "Original subject",
        "body": "Original body text here. With one extra human sentence.",
    })
    async with db_session() as db:
        draft = await db.get(Draft, draft_id)
        assert draft.edit_ratio is not None
        assert 0.0 < draft.edit_ratio < 0.5  # lightly edited

    resp = await client.get("/settings/export-judge-data")
    assert resp.status_code == 200
    row = json.loads(resp.text.splitlines()[0])
    assert row["human_decision"] == "approved"
    assert row["edit_ratio"] == draft.edit_ratio
    assert row["judge_score"] == 0.92


async def test_verbatim_approval_has_zero_edit_ratio(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            subject="S", body="B", judge_score=0.95, status="pending_review",
        ))
    await login(client, seed["email"])
    async with db_session() as db:
        draft_id = (await db.execute(select(Draft.id))).scalar_one()
    await post(client, f"/approvals/{draft_id}/approve",
               data={"subject": "S", "body": "B"})
    async with db_session() as db:
        assert (await db.get(Draft, draft_id)).edit_ratio == 0.0


# ── learning loop ────────────────────────────────────────────────────


async def test_angle_performance_attributes_replies():
    seed = await seed_workspace()
    async with db_session() as db:
        for angle, n in (("angle-A", 2), ("angle-B", 1)):
            for i in range(n):
                db.add(Draft(
                    workspace_id=seed["workspace_id"],
                    prospect_id=seed["prospect_id"],
                    body=f"{angle}-{i}", angle=angle, status="sent",
                ))
        await db.flush()
        # A reply arriving after all sends is attributed to the last draft
        # (angle-B, inserted last).
        db.add(Message(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            channel="email", direction="in", body="interested!",
            created_at=utcnow() + timedelta(minutes=5),
        ))
    async with db_session() as db:
        rows = await learning.angle_performance(db, seed["workspace_id"])
    by_angle = {r["angle"]: r for r in rows}
    assert by_angle["angle-A"]["sends"] == 2
    assert by_angle["angle-A"]["replies"] == 0
    assert by_angle["angle-B"]["replies"] == 1
    assert rows[0]["angle"] == "angle-B"  # sorted by reply rate


async def test_judge_calibration_recommends_threshold():
    seed = await seed_workspace()
    async with db_session() as db:
        for i in range(12):  # ≥ MIN_REVIEWED_PER_BAND, all approved at ≥0.9
            db.add(Draft(
                workspace_id=seed["workspace_id"],
                prospect_id=seed["prospect_id"],
                body=f"d{i}", judge_score=0.93, status="sent",
                reviewed_by=seed["user_id"], edit_ratio=0.0,
            ))
        # A low band with rejections must not extend the recommendation.
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            body="bad", judge_score=0.65, status="rejected",
            reviewed_by=seed["user_id"],
        ))
    async with db_session() as db:
        cal = await learning.judge_calibration(db, seed["workspace_id"])
    assert cal["recommended_auto_approve_score"] == 0.9
    top = cal["bands"][0]
    assert top["reviewed"] == 12 and top["approval_rate"] == 1.0


# ── Slack notifications ──────────────────────────────────────────────


async def test_killswitch_pause_notifies_slack():
    seed = await seed_workspace()
    posts = []

    class FakeResp:
        def raise_for_status(self):
            pass

    class FakeClient:
        async def post(self, url, **kw):
            posts.append((url, kw))
            return FakeResp()

    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "slack",
            {"webhook_url": "https://hooks.slack.com/services/T/B/x"},
        )
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.killswitch = {"max_llm_cost_usd": 1.0}
        db.add(Draft(
            workspace_id=ws.id, prospect_id=seed["prospect_id"],
            body="expensive", status="rejected", compose_cost_usd=5.0,
        ))
        await db.flush()
        with patch("engine.services.slack.get_client", return_value=FakeClient()):
            from engine.services.killswitch import evaluate_killswitch

            breaches = await evaluate_killswitch(db, ws)
    assert breaches
    assert posts and "Kill-switch" in posts[0][1]["json"]["text"]


async def test_slack_notify_is_noop_without_credentials():
    seed = await seed_workspace()
    from engine.services import slack

    async with db_session() as db:
        assert await slack.notify(db, seed["workspace_id"], "hello") is False


# ── deliverability warm-up ───────────────────────────────────────────


async def test_warmup_caps_early_email_volume(monkeypatch):
    from engine import config
    from engine.services.suppression import SendBlocked, check_can_send

    seed = await seed_workspace()
    monkeypatch.setattr(config.get_settings(), "warmup_start_per_day", 2)
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        await check_can_send(db, ws, "email", "a@x.test")
        await check_can_send(db, ws, "email", "b@x.test")
        blocked = False
        try:
            await check_can_send(db, ws, "email", "c@x.test")
        except SendBlocked:
            blocked = True
        assert blocked  # day-0 warm-up cap of 2, despite the 200/day platform cap


async def test_warmup_ramp_grows_with_domain_age(monkeypatch):
    from engine import config
    from engine.services.deliverability import warmup_email_cap

    seed = await seed_workspace()
    monkeypatch.setattr(config.get_settings(), "warmup_start_per_day", 10)
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        db.add(Message(
            workspace_id=ws.id, channel="email", direction="out", body="first",
            created_at=utcnow() - timedelta(days=10),
        ))
        await db.flush()
        cap = await warmup_email_cap(db, ws)
    assert cap == min(200, int(10 * 1.25 ** 10))  # ~93/day on day 10


# ── WhatsApp channel ─────────────────────────────────────────────────


async def test_whatsapp_send_routes_to_sink():
    from engine.services.whatsapp import send_whatsapp

    seed = await seed_workspace()
    calls = []

    async def fake_twilio(sid, token, from_number, to, body):
        calls.append((to, body))
        return {"sid": "SM123"}

    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "twilio", {
            "account_sid": "AC1", "auth_token": "tok", "from_number": "+15550001111",
        })
        await db.flush()
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        with patch("engine.services.whatsapp._twilio_send",
                   new=AsyncMock(side_effect=fake_twilio)):
            message = await send_whatsapp(
                db, ws, prospect, to_phone=prospect.phone, body="hello"
            )
        assert message.channel == "whatsapp"
    assert calls[0][0] == "+15550000000"  # sink phone, not the prospect
    assert "intended for +254700000001" in calls[0][1]


def _twilio_sig(auth_token: str, url: str, form: dict) -> str:
    data = url + "".join(k + v for k, v in sorted(form.items()))
    return base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


async def test_whatsapp_stop_suppresses(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "twilio", {
            "account_sid": "AC1", "auth_token": "tok", "from_number": "+15550001111",
        })
    form = {"Body": "STOP", "From": "whatsapp:+254700000001", "MessageSid": "SM9"}
    sig = _twilio_sig("tok", "http://testserver/webhooks/acme/whatsapp", form)
    with patch("engine.services.whatsapp._twilio_send",
               new=AsyncMock(return_value={"sid": "SM10"})):
        resp = await client.post(
            "/webhooks/acme/whatsapp", data=form,
            headers={"X-Twilio-Signature": sig},
        )
    assert resp.json()["status"] == "opted_out"
    async with db_session() as db:
        from engine.services.suppression import is_suppressed

        assert await is_suppressed(
            db, seed["workspace_id"], "whatsapp", "+254700000001"
        )


async def test_whatsapp_inbound_gets_whatsapp_reply_draft(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "twilio", {
            "account_sid": "AC1", "auth_token": "tok", "from_number": "+15550001111",
        })
    form = {
        "Body": "Interested — tell me more",
        "From": "whatsapp:+254700000001",
        "MessageSid": "SM11",
    }
    sig = _twilio_sig("tok", "http://testserver/webhooks/acme/whatsapp", form)
    resp = await client.post(
        "/webhooks/acme/whatsapp", data=form,
        headers={"X-Twilio-Signature": sig},
    )
    assert resp.json()["status"] == "queued"
    warm = {"intent": "warm", "reply": "Great! Here's the link.",
            "escalate": False, "escalation_reason": ""}
    with mock_llm([warm]):
        assert await process_one()
    async with db_session() as db:
        draft = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalar_one()
        assert draft.channel == "whatsapp"
        assert draft.status == "pending_review"  # default approval gate


# ── booking reminders ────────────────────────────────────────────────


async def test_booking_reminder_scheduled_and_sent():
    seed = await seed_workspace()
    async with db_session() as db:
        # Keep the campaign out of the pass so only the reminder job exists.
        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.status = "draft"
        await set_credentials(
            db, seed["workspace_id"], "africastalking",
            {"username": "sandbox", "api_key": "atk", "webhook_token": "tok-123456789012"},
        )
        db.add(Booking(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            provider_uid="bk_r1", status="confirmed",
            start_time=utcnow() + timedelta(hours=12),
        ))
    await run_scheduler_pass()
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "booking_reminder")
        )).scalar_one()
        assert job.idempotency_key == f"remind:{job.payload['booking_id']}"

    sent = []

    async def fake_at_send(username, api_key, to, body, sender_id):
        sent.append((to, body))
        return {"SMSMessageData": {"Recipients": [
            {"status": "Success", "messageId": "at_r"}]}}

    with patch("engine.services.smser._at_send",
               new=AsyncMock(side_effect=fake_at_send)):
        assert await process_one()
    assert sent and "Reminder" in sent[0][1]
    async with db_session() as db:
        booking = (await db.execute(select(Booking))).scalar_one()
        assert booking.meta.get("reminder_sent_at")

    # Second pass: the idempotency key prevents a duplicate reminder.
    await run_scheduler_pass()
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "booking_reminder")
        )).scalars().all()
        assert len(jobs) == 1


async def test_reminder_skips_suppressed_number():
    from engine.services.suppression import suppress

    seed = await seed_workspace()
    async with db_session() as db:
        await suppress(db, seed["workspace_id"], "sms", "+254700000001", "opt_out")
        db.add(Booking(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            provider_uid="bk_r2", status="confirmed",
            start_time=utcnow() + timedelta(hours=2),
        ))
        await db.flush()
        booking_id = (await db.execute(select(Booking.id))).scalar_one()
        await enqueue(db, "booking_reminder", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
            "booking_id": booking_id,
        })
    sent = []
    with patch("engine.services.smser._at_send",
               new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
        assert await process_one()
    assert not sent  # suppression always wins, even for transactional sends


# ── weekly digest ────────────────────────────────────────────────────


async def test_weekly_digest_emails_admins():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend", {"api_key": "re_test"}
        )
        db.add(Message(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            channel="email", direction="out", body="sent last week",
        ))
        await enqueue(db, "weekly_digest", {"workspace_id": seed["workspace_id"]})
    sent = []

    async def fake_resend(api_key, payload, idempotency_key=None):
        sent.append(payload)
        return {"id": "re_digest"}

    with patch("engine.services.emailer._resend_send",
               new=AsyncMock(side_effect=fake_resend)):
        assert await process_one()
    assert len(sent) == 1
    assert sent[0]["to"] == [seed["email"]]
    assert "weekly outreach digest" in sent[0]["subject"]
    assert "Emails sent" in sent[0]["text"]

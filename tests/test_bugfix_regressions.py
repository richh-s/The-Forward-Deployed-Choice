"""Regressions for the audit-driven bug fixes: reply/touch-ceiling
interaction, opt-out enforcement across channels, kill-switch resume,
campaign-angle plumbing, webhook robustness, credential merge, and the
queue/LLM permanent-failure paths."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from engine.db import db_session
from engine.models import AuditLog, Booking, Draft, Job, Prospect, Workspace
from engine.queue import PermanentJobError, enqueue, process_one
from engine.services.credentials import (
    CredentialValidationError,
    get_credentials,
    set_credentials,
    validate_credential_payload,
)
from engine.services.llm import LLMResult
from engine.services.suppression import SendBlocked, check_can_send
from tests.conftest import csrf_for, login, post, seed_workspace

# ── touch ceiling vs replies, and opted-out enforcement ──────────────


async def test_reply_send_bypasses_touch_ceiling():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.touch_count = 99  # far past the ceiling
        with pytest.raises(SendBlocked, match="touch ceiling"):
            await check_can_send(db, ws, "email", prospect.email, prospect)
        # A reply to something the prospect sent must still go out.
        await check_can_send(
            db, ws, "email", prospect.email, prospect, is_reply=True
        )


async def test_opted_out_stage_blocks_send_on_every_channel():
    """A channel-scoped STOP sets stage=opted_out — an email draft approved
    before the STOP must not deliver even without an email suppression row."""
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.stage = "opted_out"
        with pytest.raises(SendBlocked, match="opted out"):
            await check_can_send(db, ws, "email", prospect.email, prospect)


async def test_whatsapp_stop_opts_prospect_out(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "twilio",
            {"account_sid": "AC1", "auth_token": "tok-tok-tok-tok"},
        )
    from engine.webhooks import verify as verify_mod

    with patch.object(verify_mod, "verify_twilio"), patch(
        "engine.routes.webhooks.verify_twilio"
    ):
        resp = await client.post(
            f"/webhooks/{seed['slug']}/whatsapp",
            data={
                "Body": "STOP",
                "From": "whatsapp:+254700000001",
                "MessageSid": "SM1",
            },
        )
    assert resp.status_code == 200
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "opted_out"
        assert prospect.next_followup_at is None


# ── kill-switch: resume sticks ───────────────────────────────────────


async def test_killswitch_resume_is_not_undone_next_pass():
    from engine.services.killswitch import evaluate_killswitch

    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.killswitch = {"max_llm_cost_usd": 1.0}
        db.add(Draft(
            workspace_id=ws.id, prospect_id=seed["prospect_id"],
            body="expensive", status="rejected", compose_cost_usd=5.0,
        ))
        await db.flush()
        assert await evaluate_killswitch(db, ws)
        assert ws.outbound_paused
    # Admin reviews and resumes — the audit row is the watermark.
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.outbound_paused = False
        ws.pause_reason = None
        db.add(AuditLog(workspace_id=ws.id, action="outbound_resumed", detail={}))
    # The next scheduler pass re-evaluates: only NEW spend counts.
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        breaches = await evaluate_killswitch(db, ws)
        assert breaches == []
        assert not ws.outbound_paused


# ── campaign angle reaches the composer ──────────────────────────────


async def test_campaign_angle_reaches_first_touch_compose():
    seed = await seed_workspace()
    captured = {}

    async def fake_complete(db, workspace_id, **kwargs):
        captured.setdefault("prompts", []).append(
            kwargs["messages"][0]["content"]
        )
        return LLMResult(
            text=json.dumps({
                "subject": "s", "body": "b", "mode_used": "inquiry",
                "grounding_notes": "n",
                # judge schema keys (extra keys are harmless for compose)
                "signal_grounding": 1, "mode_compliance": 1, "tone": 1,
                "structure": 1, "hallucination_free": 1, "feedback": "ok",
            }),
            model="claude-opus-5", input_tokens=1, output_tokens=1,
        )

    async with db_session() as db:
        from engine.models import Campaign

        campaign = await db.get(Campaign, seed["campaign_id"])
        campaign.playbook = {"angle": "post-funding scaling pain"}
        await enqueue(db, "compose_draft", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
            "campaign_id": seed["campaign_id"],
            "touch_number": 1,
        })
    with patch(
        "engine.services.llm.complete", new=AsyncMock(side_effect=fake_complete)
    ):
        assert await process_one()
    assert any(
        "post-funding scaling pain" in p for p in captured["prompts"]
    ), "campaign angle never reached the composer prompt"
    async with db_session() as db:
        draft = (await db.execute(select(Draft))).scalars().first()
        assert draft is not None
        assert draft.angle == "post-funding scaling pain"


# ── reject → fresh compose with feedback ─────────────────────────────


async def test_reject_enqueues_recompose_with_feedback(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        draft = Draft(
            workspace_id=seed["workspace_id"],
            prospect_id=seed["prospect_id"],
            campaign_id=seed["campaign_id"],
            body="too pushy",
            status="pending_review",
            touch_number=1,
        )
        db.add(draft)
        await db.flush()
        draft_id = draft.id
    await login(client, seed["email"])
    resp = await post(
        client, f"/approvals/{draft_id}/reject", data={"reason": "Too pushy"}
    )
    assert resp.status_code == 303
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.idempotency_key == f"recompose:{draft_id}")
        )).scalars().first()
        assert job is not None
        assert job.payload["rejection_feedback"] == "Too pushy"


# ── overnight send windows ───────────────────────────────────────────


def test_overnight_send_window():
    from engine.services import scheduler as sched

    campaign = SimpleNamespace(
        id="c1", timezone="UTC",
        send_window_start_hour=18, send_window_end_hour=8,
    )
    with patch.object(
        sched, "_campaign_now",
        return_value=datetime(2026, 1, 1, 23, 0, tzinfo=UTC),
    ):
        assert sched._in_send_window(campaign)
    with patch.object(
        sched, "_campaign_now",
        return_value=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    ):
        assert not sched._in_send_window(campaign)


# ── credentials: merge + unknown fields + decrypt failure ────────────


def test_unknown_credential_field_is_an_error_not_silent():
    with pytest.raises(CredentialValidationError, match="apikey"):
        validate_credential_payload("resend", {"apikey": "re_123"})


async def test_credential_save_merges_instead_of_wiping(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await post(
        client, "/settings/credentials/resend",
        data={"payload_json": json.dumps(
            {"api_key": "re_1", "webhook_secret": "whsec_abc"}
        )},
    )
    assert resp.status_code == 303
    # Re-save only the api_key — the webhook_secret must survive.
    resp = await post(
        client, "/settings/credentials/resend",
        data={"payload_json": json.dumps({"api_key": "re_2"})},
    )
    assert resp.status_code == 303
    async with db_session() as db:
        creds = await get_credentials(db, seed["workspace_id"], "resend")
    assert creds == {"api_key": "re_2", "webhook_secret": "whsec_abc"}


async def test_undecryptable_credentials_read_as_unconfigured():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend", {"api_key": "re_1"}
        )
    with patch(
        "engine.services.credentials.decrypt_credentials",
        side_effect=ValueError("bad key"),
    ):
        async with db_session() as db:
            assert await get_credentials(
                db, seed["workspace_id"], "resend"
            ) is None


# ── inbound reply matching ───────────────────────────────────────────


def test_extract_email_handles_display_name_and_object():
    from engine.routes.webhooks import _extract_email

    assert _extract_email("Jane Doe <Jane@X.com>") == "jane@x.com"
    assert _extract_email({"email": "a@b.co"}) == "a@b.co"
    assert _extract_email("plain@addr.io") == "plain@addr.io"
    assert _extract_email(None) == ""


# ── SMS provider rejection is permanent; 'sending' guard holds ───────


async def test_at_rejection_is_permanent():
    from engine.services.smser import send_sms

    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "africastalking",
            {"username": "sandbox", "api_key": "atsk_x"},
        )
        await db.flush()
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        rejected = {"SMSMessageData": {"Recipients": [
            {"status": "InvalidPhoneNumber", "messageId": None}
        ]}}
        with patch(
            "engine.services.smser._at_send",
            new=AsyncMock(return_value=rejected),
        ):
            with pytest.raises(PermanentJobError):
                await send_sms(
                    db, ws, prospect,
                    to_phone=prospect.phone, body="hi", is_reply=True,
                )


async def test_draft_stuck_in_sending_dead_letters_not_double_sends():
    seed = await seed_workspace()
    async with db_session() as db:
        draft = Draft(
            workspace_id=seed["workspace_id"],
            prospect_id=seed["prospect_id"],
            kind="reply", channel="sms", body="hello", status="sending",
        )
        db.add(draft)
        await db.flush()
        await enqueue(db, "send_draft", {"draft_id": draft.id})
    assert await process_one()
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "send_draft")
        )).scalars().first()
        assert job.status == "dead"
        assert "may already have delivered" in job.last_error


# ── booking reschedule updates in place ──────────────────────────────


async def test_reschedule_with_new_uid_updates_existing_booking():
    from engine.services.booking import record_booking_event

    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        created = await record_booking_event(db, ws, "BOOKING_CREATED", {
            "uid": "uid-1",
            "startTime": "2026-09-01T10:00:00Z",
            "metadata": {"prospect_id": seed["prospect_id"]},
        })
        assert created.status == "confirmed"
        rescheduled = await record_booking_event(db, ws, "BOOKING_RESCHEDULED", {
            "uid": "uid-2",  # Cal.com mints a NEW uid on reschedule
            "startTime": "2026-09-02T10:00:00Z",
            "metadata": {"prospect_id": seed["prospect_id"]},
        })
        assert rescheduled.id == created.id  # updated, not duplicated
        assert rescheduled.provider_uid == "uid-2"
        bookings = (await db.execute(select(Booking))).scalars().all()
        assert len(bookings) == 1


async def test_malformed_booking_payload_shapes_do_not_crash():
    from engine.services.booking import record_booking_event

    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        booking = await record_booking_event(db, ws, "BOOKING_CREATED", {
            "uid": "uid-x",
            "metadata": "not-a-dict",
            "attendees": [{"email": None}, "junk", {}],
        })
        assert booking is not None


# ── CSV import robustness ────────────────────────────────────────────


async def test_ragged_csv_row_does_not_500(client: httpx.AsyncClient):
    import io as _io

    seed = await seed_workspace()
    await login(client, seed["email"])
    csv_content = (
        "email,name\n"
        "ok@x.test,Fine\n"
        "ragged@x.test,Name,EXTRA,MORE\n"  # more fields than the header
    )
    resp = await client.post(
        f"/campaigns/{seed['campaign_id']}/upload",
        data={"csrf_token": csrf_for(client)},
        files={"file": ("p.csv", _io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 303
    assert "Imported+2" in resp.headers["location"]


# ── kill-switch thresholds have a UI route ───────────────────────────


async def test_killswitch_thresholds_saved_from_settings(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await post(client, "/settings/killswitch", data={
        "opt_out_rate": "0.02", "max_llm_cost_usd": "150",
        "bounce_rate": "", "cost_per_qualified_lead": "",
    })
    assert resp.status_code == 303
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        assert ws.killswitch == {"opt_out_rate": 0.02, "max_llm_cost_usd": 150.0}


# ── prospect search + export ─────────────────────────────────────────


async def test_prospect_search_filters(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        db.add(Prospect(
            workspace_id=seed["workspace_id"],
            campaign_id=seed["campaign_id"],
            email="zed@other.test", name="Zed Zebra", company="Otherco",
        ))
    await login(client, seed["email"])
    page = await client.get("/prospects?q=Zebra")
    assert "zed@other.test" in page.text
    assert seed["prospect_email"] not in page.text


async def test_prospect_csv_export(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await client.get("/prospects.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert seed["prospect_email"] in resp.text


# ── queue hygiene ────────────────────────────────────────────────────


async def test_unknown_job_type_dead_letters_immediately():
    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "no_such_handler", {}, workspace_id=seed["workspace_id"])
    assert await process_one()
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "no_such_handler")
        )).scalars().first()
        assert job.status == "dead"
        assert job.attempts == 1  # no retries burned


async def test_job_for_deleted_prospect_dead_letters_immediately():
    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "compose_draft", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": "gone-gone-gone",
        }, workspace_id=seed["workspace_id"])
    assert await process_one()
    async with db_session() as db:
        job = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().first()
        assert job.status == "dead"
        assert job.attempts == 1


async def test_gdpr_delete_removes_pending_jobs(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "compose_draft", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
        }, workspace_id=seed["workspace_id"])
    await login(client, seed["email"])
    resp = await post(client, f"/prospects/{seed['prospect_id']}/delete")
    assert resp.status_code == 303
    async with db_session() as db:
        jobs = (await db.execute(
            select(Job).where(Job.type == "compose_draft")
        )).scalars().all()
        assert jobs == []


# ── daily counter respects a campaign-local date key ─────────────────


async def test_daily_counter_date_key_buckets_separately():
    from engine.services.suppression import increment_daily_counter

    seed = await seed_workspace()
    async with db_session() as db:
        # Same channel, two different local dates → independent caps.
        await increment_daily_counter(
            db, seed["workspace_id"], "q:c1", cap=1, date_key="2026-08-27"
        )
        await increment_daily_counter(
            db, seed["workspace_id"], "q:c1", cap=1, date_key="2026-08-28"
        )
        with pytest.raises(SendBlocked):
            await increment_daily_counter(
                db, seed["workspace_id"], "q:c1", cap=1, date_key="2026-08-28"
            )

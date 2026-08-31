"""Webhook handler behaviour.

test_webhook_security.py covers the perimeter (is a request authentic?).
This file covers what the handlers do once a request is authentic: status
transitions, compliance commands, prospect matching, tenant isolation, and
that side effects are enqueued exactly once.
"""
import hashlib
import hmac
import json

import httpx
import pytest
from sqlalchemy import select

from engine.db import db_session
from engine.models import (
    Booking,
    Job,
    Message,
    Prospect,
    Suppression,
    Workspace,
)
from engine.services.suppression import is_suppressed
from tests.conftest import seed_workspace
from tests.signing import (
    CALCOM_SECRET,
    calcom_event,
    configure,
    resend_event,
    svix_headers,
    telegram_headers,
    twilio_headers,
)

# ── helpers ──────────────────────────────────────────────────────────


async def jobs_of(job_type: str) -> list[Job]:
    async with db_session() as db:
        rows = await db.execute(select(Job).where(Job.type == job_type))
        return list(rows.scalars().all())


async def suppressions(channel: str | None = None) -> list[Suppression]:
    async with db_session() as db:
        stmt = select(Suppression)
        if channel:
            stmt = stmt.where(Suppression.channel == channel)
        return list((await db.execute(stmt)).scalars().all())


async def inbound_messages(channel: str) -> list[Message]:
    async with db_session() as db:
        rows = await db.execute(
            select(Message).where(
                Message.channel == channel, Message.direction == "in"
            )
        )
        return list(rows.scalars().all())


async def get_prospect(prospect_id: str) -> Prospect:
    async with db_session() as db:
        return await db.get(Prospect, prospect_id)


async def add_message(seed: dict, provider_message_id: str) -> str:
    """An outbound email awaiting delivery events."""
    async with db_session() as db:
        msg = Message(
            workspace_id=seed["workspace_id"],
            prospect_id=seed["prospect_id"],
            channel="email",
            direction="out",
            subject="Hello",
            body="Body",
            provider_message_id=provider_message_id,
            status="sent",
        )
        db.add(msg)
        await db.flush()
        return msg.id


# ── Resend: delivery events ──────────────────────────────────────────


async def test_delivered_event_advances_message_status(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")
    message_id = await add_message(seed, "email_abc")

    body, headers = resend_event("email.delivered", {"email_id": "email_abc"})
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200
    async with db_session() as db:
        assert (await db.get(Message, message_id)).status == "delivered"


async def test_opened_and_clicked_statuses(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")
    message_id = await add_message(seed, "email_abc")

    for i, (event, expected) in enumerate(
        [("email.opened", "opened"), ("email.clicked", "clicked")]
    ):
        body, headers = resend_event(
            event, {"email_id": "email_abc"}, svix_id=f"msg_{i}"
        )
        await client.post("/webhooks/acme/resend", content=body, headers=headers)
        async with db_session() as db:
            assert (await db.get(Message, message_id)).status == expected


async def test_bounce_suppresses_recipient(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")
    await add_message(seed, "email_abc")

    body, headers = resend_event(
        "email.bounced",
        {"email_id": "email_abc", "to": [seed["prospect_email"]]},
    )
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200
    rows = await suppressions("email")
    assert [(s.address, s.reason) for s in rows] == [
        (seed["prospect_email"], "bounce")
    ]


async def test_complaint_suppresses_with_complaint_reason(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.complained", {"to": [seed["prospect_email"]]}
    )
    await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert [s.reason for s in await suppressions("email")] == ["complaint"]


async def test_bounce_with_bare_string_recipient(client: httpx.AsyncClient):
    """Some payloads carry `to` as a bare string, not a list."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.bounced", {"to": seed["prospect_email"]}
    )
    await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert [s.address for s in await suppressions("email")] == [
        seed["prospect_email"]
    ]


async def test_delivery_event_for_unknown_message_is_harmless(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event("email.delivered", {"email_id": "nope"})
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200


# ── Resend: inbound replies ──────────────────────────────────────────


async def test_inbound_reply_records_message_and_enqueues(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received",
        {
            "from": seed["prospect_email"],
            "subject": "Re: intro",
            "text": "Sounds interesting, tell me more.",
        },
    )
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200
    messages = await inbound_messages("email")
    assert len(messages) == 1
    assert messages[0].body == "Sounds interesting, tell me more."
    assert messages[0].subject == "Re: intro"

    queued = await jobs_of("inbound_message")
    assert len(queued) == 1
    assert queued[0].payload["channel"] == "email"
    assert queued[0].payload["prospect_id"] == seed["prospect_id"]
    assert queued[0].idempotency_key == f"inbound:{messages[0].id}"


async def test_inbound_reply_with_display_name_sender(client: httpx.AsyncClient):
    """`From: Jane Doe <jane@x.test>` must still resolve to the prospect."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received",
        {"from": f"Jane Doe <{seed['prospect_email'].upper()}>", "text": "Hi"},
    )
    await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert len(await inbound_messages("email")) == 1


async def test_inbound_reply_with_object_sender(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received",
        {"from": {"email": seed["prospect_email"]}, "text": "Hi"},
    )
    await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert len(await inbound_messages("email")) == 1


async def test_inbound_reply_from_unknown_sender_is_ignored(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received", {"from": "stranger@nowhere.test", "text": "Hi"}
    )
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200
    assert await inbound_messages("email") == []
    assert await jobs_of("inbound_message") == []


async def test_inbound_reply_body_is_truncated(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received", {"from": seed["prospect_email"], "text": "x" * 9000}
    )
    await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert len((await inbound_messages("email"))[0].body) == 5000


async def test_resend_malformed_json_rejected(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    payload = b"{not json"
    resp = await client.post(
        "/webhooks/acme/resend", content=payload, headers=svix_headers(payload)
    )
    assert resp.status_code == 400


async def test_resend_non_object_json_rejected(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    payload = b'["a list"]'
    resp = await client.post(
        "/webhooks/acme/resend", content=payload, headers=svix_headers(payload)
    )
    assert resp.status_code == 400


async def test_resend_unknown_event_type_is_accepted_quietly(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event("email.queued", {"email_id": "x"})
    resp = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert resp.status_code == 200
    assert await jobs_of("inbound_message") == []


async def test_replayed_inbound_reply_enqueues_once(client: httpx.AsyncClient):
    """Provider retries must not produce a second reply job."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "resend")

    body, headers = resend_event(
        "email.received", {"from": seed["prospect_email"], "text": "Hi"}
    )
    first = await client.post("/webhooks/acme/resend", content=body, headers=headers)
    second = await client.post("/webhooks/acme/resend", content=body, headers=headers)

    assert first.json() == {"received": True}
    assert second.json() == {"received": True, "duplicate": True}
    assert len(await jobs_of("inbound_message")) == 1


# ── Africa's Talking SMS ─────────────────────────────────────────────

SMS_URL = "/webhooks/acme/sms/africastalking-url-token-32chars"


class SendRecorder:
    """Stands in for a carrier: records the confirmation replies the
    compliance branches send, without touching the network."""

    def __init__(self):
        self.sent: list[dict] = []

    async def __call__(self, db, workspace, prospect, *, to_phone, body, **kw):
        self.sent.append({"to": to_phone, "body": body, **kw})
        return None

    @property
    def bodies(self) -> list[str]:
        return [s["body"] for s in self.sent]


@pytest.fixture
def sms_carrier(monkeypatch):
    recorder = SendRecorder()
    monkeypatch.setattr("engine.routes.webhooks.send_sms", recorder)
    return recorder


@pytest.fixture
def whatsapp_carrier(monkeypatch):
    recorder = SendRecorder()
    monkeypatch.setattr("engine.services.whatsapp.send_whatsapp", recorder)
    return recorder


async def sms_form(**overrides) -> dict:
    form = {
        "from": "+254700000001", "to": "12345",
        "text": "Hello", "id": "at_1", "date": "2026-08-30",
    }
    form.update(overrides)
    return form


async def test_inbound_sms_records_and_enqueues(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    resp = await client.post(SMS_URL, data=await sms_form(text="Yes, interested"))

    assert resp.json() == {"status": "queued"}
    messages = await inbound_messages("sms")
    assert [m.body for m in messages] == ["Yes, interested"]
    queued = await jobs_of("inbound_message")
    assert len(queued) == 1
    assert queued[0].payload["channel"] == "sms"


async def test_stop_suppresses_and_halts_sequence(
    client: httpx.AsyncClient, sms_carrier
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    resp = await client.post(SMS_URL, data=await sms_form(text="STOP"))

    assert resp.json() == {"status": "opted_out"}
    assert [(s.channel, s.reason) for s in await suppressions()] == [
        ("sms", "opt_out")
    ]
    prospect = await get_prospect(seed["prospect_id"])
    assert prospect.stage == "opted_out"
    assert prospect.next_followup_at is None
    # STOP must be acknowledged, and that ack bypasses the suppression it
    # just created — otherwise it would be blocked by its own opt-out.
    assert "unsubscribed" in sms_carrier.bodies[0]
    assert sms_carrier.sent[0]["skip_policy_checks"] is True


@pytest.mark.parametrize("command", ["stop", "UNSUB", "Unsubscribe", "QUIT", "CANCEL"])
async def test_all_opt_out_synonyms_and_casings(
    client: httpx.AsyncClient, sms_carrier, command
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    resp = await client.post(SMS_URL, data=await sms_form(text=f"  {command} "))

    assert resp.json() == {"status": "opted_out"}
    assert len(await suppressions("sms")) == 1


async def test_start_resubscribes(client: httpx.AsyncClient, sms_carrier):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    await client.post(SMS_URL, data=await sms_form(text="STOP", id="at_1"))
    assert len(await suppressions("sms")) == 1

    resp = await client.post(SMS_URL, data=await sms_form(text="START", id="at_2"))

    assert resp.json() == {"status": "resubscribed"}
    assert await suppressions("sms") == []
    assert "resubscribed" in sms_carrier.bodies[-1]


async def test_help_replies_with_support_contact(
    client: httpx.AsyncClient, sms_carrier
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.playbook = dict(ws.playbook or {}, support_contact="help@acme.test")

    resp = await client.post(SMS_URL, data=await sms_form(text="HELP"))

    assert resp.json() == {"status": "help_sent"}
    assert "Reply STOP to unsubscribe." in sms_carrier.bodies[0]
    assert "help@acme.test" in sms_carrier.bodies[0]


async def test_help_without_support_contact_still_replies(
    client: httpx.AsyncClient, sms_carrier
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    await client.post(SMS_URL, data=await sms_form(text="HELP"))

    assert sms_carrier.bodies[0] == "Reply STOP to unsubscribe."


async def test_opt_out_confirmation_failure_does_not_break_opt_out(
    client: httpx.AsyncClient, monkeypatch
):
    """The suppression is the legally important half; a carrier outage on
    the courtesy ack must not roll it back."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    async def exploding(*a, **kw):
        raise RuntimeError("carrier down")

    monkeypatch.setattr("engine.routes.webhooks.send_sms", exploding)

    resp = await client.post(SMS_URL, data=await sms_form(text="STOP"))

    assert resp.json() == {"status": "opted_out"}
    assert len(await suppressions("sms")) == 1
    assert (await get_prospect(seed["prospect_id"])).stage == "opted_out"


async def test_sms_from_unknown_number_is_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    resp = await client.post(SMS_URL, data=await sms_form(**{"from": "+15559999999"}))

    assert resp.json() == {"status": "unknown_sender"}
    assert await jobs_of("inbound_message") == []


async def test_sms_without_sender_is_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    resp = await client.post(SMS_URL, data=await sms_form(**{"from": ""}))

    assert resp.json() == {"status": "ignored"}


async def test_replayed_sms_is_deduped_by_provider_id(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    form = await sms_form(text="Interested")
    first = await client.post(SMS_URL, data=form)
    second = await client.post(SMS_URL, data=form)

    assert first.json() == {"status": "queued"}
    assert second.json() == {"status": "duplicate"}
    assert len(await jobs_of("inbound_message")) == 1


async def test_replayed_sms_without_id_dedups_on_content(client: httpx.AsyncClient):
    """AT sometimes omits `id`; a content fingerprint must still dedup."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "africastalking")

    form = await sms_form(text="Interested", id="")
    await client.post(SMS_URL, data=form)
    second = await client.post(SMS_URL, data=form)

    assert second.json() == {"status": "duplicate"}
    assert len(await jobs_of("inbound_message")) == 1


# ── Twilio WhatsApp ──────────────────────────────────────────────────

WA_URL = "http://testserver/webhooks/acme/whatsapp"


def wa_form(**overrides) -> dict[str, str]:
    form = {
        "Body": "Hello", "From": "whatsapp:+254700000001",
        "To": "whatsapp:+15550001111", "MessageSid": "SM1",
    }
    form.update(overrides)
    return form


async def post_whatsapp(client: httpx.AsyncClient, **overrides):
    form = wa_form(**overrides)
    return await client.post(
        "/webhooks/acme/whatsapp", data=form, headers=twilio_headers(WA_URL, form)
    )


async def test_inbound_whatsapp_records_and_enqueues(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_whatsapp(client, Body="Tell me more")

    assert resp.json() == {"status": "queued"}
    assert [m.body for m in await inbound_messages("whatsapp")] == ["Tell me more"]
    assert (await jobs_of("inbound_message"))[0].payload["channel"] == "whatsapp"


async def test_whatsapp_stop_halts_every_channel(
    client: httpx.AsyncClient, whatsapp_carrier
):
    """A STOP on WhatsApp opts the prospect out of the whole sequence, not
    just this channel."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_whatsapp(client, Body="STOP")

    assert resp.json() == {"status": "opted_out"}
    assert [(s.channel, s.reason) for s in await suppressions()] == [
        ("whatsapp", "opt_out")
    ]
    prospect = await get_prospect(seed["prospect_id"])
    assert prospect.stage == "opted_out"
    assert prospect.next_followup_at is None
    assert "unsubscribed" in whatsapp_carrier.bodies[0]


async def test_whatsapp_start_resubscribes(
    client: httpx.AsyncClient, whatsapp_carrier
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    await post_whatsapp(client, Body="STOP", MessageSid="SM1")
    resp = await post_whatsapp(client, Body="START", MessageSid="SM2")

    assert resp.json() == {"status": "resubscribed"}
    assert await suppressions("whatsapp") == []


async def test_whatsapp_help_replies(client: httpx.AsyncClient, whatsapp_carrier):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_whatsapp(client, Body="HELP")

    assert resp.json() == {"status": "help_sent"}
    assert "Reply STOP to unsubscribe." in whatsapp_carrier.bodies[0]


async def test_whatsapp_from_unknown_number_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_whatsapp(client, From="whatsapp:+15559999999")

    assert resp.json() == {"status": "unknown_sender"}
    assert await jobs_of("inbound_message") == []


async def test_replayed_whatsapp_is_deduped(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    await post_whatsapp(client, Body="Interested")
    second = await post_whatsapp(client, Body="Interested")

    assert second.json() == {"status": "duplicate"}
    assert len(await jobs_of("inbound_message")) == 1


async def test_whatsapp_rejects_bad_signature(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await client.post(
        "/webhooks/acme/whatsapp", data=wa_form(),
        headers={"X-Twilio-Signature": "not-the-signature"},
    )
    assert resp.status_code == 401


# ── Telegram ─────────────────────────────────────────────────────────


async def post_telegram(client: httpx.AsyncClient, update: dict, **kw):
    return await client.post(
        "/webhooks/acme/telegram",
        content=json.dumps(update).encode(),
        headers=telegram_headers(),
        **kw,
    )


def tg_update(text: str, *, chat_id: str = "555", update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": chat_id}, "text": text},
    }


async def test_telegram_requires_secret_header(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await client.post(
        "/webhooks/acme/telegram", content=json.dumps(tg_update("hi")).encode()
    )
    assert resp.status_code == 401


async def test_telegram_rejects_wrong_secret(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await client.post(
        "/webhooks/acme/telegram",
        content=json.dumps(tg_update("hi")).encode(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 401


async def test_telegram_deep_link_binds_chat_to_prospect(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(client, tg_update(f"/start {seed['prospect_id']}"))

    assert resp.json() == {"ok": True, "linked": True}
    assert (await get_prospect(seed["prospect_id"])).telegram_chat_id == "555"
    replies = await jobs_of("telegram_raw_send")
    assert "connected to Acme" in replies[0].payload["text"]


async def test_telegram_deep_link_cannot_bind_a_foreign_prospect(
    client: httpx.AsyncClient,
):
    """The /start payload is attacker-controlled: it must never link a chat
    to a prospect in another workspace."""
    seed = await seed_workspace(slug="acme")
    other = await seed_workspace(slug="other", admin_email="admin@other.test")
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(client, tg_update(f"/start {other['prospect_id']}"))

    assert resp.json() == {"ok": True}
    assert (await get_prospect(other["prospect_id"])).telegram_chat_id is None


async def test_telegram_bare_start_returns_chat_id(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(client, tg_update("/start"))

    assert resp.json() == {"ok": True}
    assert "555" in (await jobs_of("telegram_raw_send"))[0].payload["text"]


async def test_telegram_stop_opts_out(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")
    await post_telegram(client, tg_update(f"/start {seed['prospect_id']}"))

    resp = await post_telegram(client, tg_update("/stop", update_id=2))

    assert resp.json() == {"ok": True, "opted_out": True}
    # Suppression is stored and re-read through the same normalization, so
    # the round-trip is what matters, not the stored spelling of the id.
    assert [s.channel for s in await suppressions()] == ["telegram"]
    async with db_session() as db:
        assert await is_suppressed(db, seed["workspace_id"], "telegram", "555")
    prospect = await get_prospect(seed["prospect_id"])
    assert prospect.stage == "opted_out"
    assert prospect.next_followup_at is None


async def test_telegram_linked_chat_message_is_queued(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")
    await post_telegram(client, tg_update(f"/start {seed['prospect_id']}"))

    resp = await post_telegram(client, tg_update("What does it cost?", update_id=2))

    assert resp.json() == {"ok": True, "queued": True}
    assert [m.body for m in await inbound_messages("telegram")] == [
        "What does it cost?"
    ]
    assert (await jobs_of("inbound_message"))[0].payload["channel"] == "telegram"


async def test_telegram_unlinked_chat_gets_guidance_not_a_job(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(client, tg_update("hello?"))

    assert resp.json() == {"ok": True, "ignored": "unlinked chat"}
    assert await jobs_of("inbound_message") == []
    assert "isn't linked" in (await jobs_of("telegram_raw_send"))[0].payload["text"]


async def test_telegram_duplicate_update_id_is_dropped(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")
    await post_telegram(client, tg_update(f"/start {seed['prospect_id']}"))

    await post_telegram(client, tg_update("hi", update_id=2))
    second = await post_telegram(client, tg_update("hi", update_id=2))

    assert second.json() == {"ok": True, "duplicate": True}
    assert len(await jobs_of("inbound_message")) == 1


async def test_telegram_non_message_update_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(client, {"update_id": 7, "edited_message": {}})

    assert resp.json() == {"ok": True, "ignored": "no message"}


async def test_telegram_message_without_chat_id_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await post_telegram(
        client, {"update_id": 8, "message": {"text": "hi"}}
    )

    assert resp.json() == {"ok": True, "ignored": "no chat id"}


async def test_telegram_malformed_json_rejected(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "telegram")

    resp = await client.post(
        "/webhooks/acme/telegram", content=b"{oops",
        headers=telegram_headers(),
    )
    assert resp.status_code == 400


# ── Cal.com booking lifecycle ────────────────────────────────────────


async def post_calcom(client: httpx.AsyncClient, trigger: str, payload: dict):
    body, headers = calcom_event(trigger, payload)
    return await client.post("/webhooks/acme/calcom", content=body, headers=headers)


def booking_payload(seed: dict, *, uid: str = "bk_1", **extra) -> dict:
    payload = {
        "uid": uid,
        "startTime": "2026-09-01T15:00:00Z",
        "metadata": {"prospect_id": seed["prospect_id"]},
        "attendees": [{"email": seed["prospect_email"]}],
    }
    payload.update(extra)
    return payload


async def test_booking_created_records_and_syncs_to_crm(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    resp = await post_calcom(client, "BOOKING_CREATED", booking_payload(seed))

    assert resp.json() == {"received": True}
    async with db_session() as db:
        bookings = list((await db.execute(select(Booking))).scalars().all())
    assert [b.provider_uid for b in bookings] == ["bk_1"]
    assert bookings[0].prospect_id == seed["prospect_id"]

    synced = await jobs_of("hubspot_mark_booked")
    assert len(synced) == 1
    assert synced[0].payload["booking_uid"] == "bk_1"
    assert synced[0].idempotency_key == (
        "hs_booked:bk_1:2026-09-01T15:00:00Z"
    )


async def test_reschedule_also_syncs_to_crm(client: httpx.AsyncClient):
    """The meeting time changed — the CRM must not keep the stale slot."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    await post_calcom(client, "BOOKING_CREATED", booking_payload(seed))
    resp = await post_calcom(
        client, "BOOKING_RESCHEDULED",
        booking_payload(seed, startTime="2026-09-02T16:00:00Z"),
    )

    assert resp.json() == {"received": True}
    synced = await jobs_of("hubspot_mark_booked")
    assert len(synced) == 2
    assert {j.payload["booking_time"] for j in synced} == {
        "2026-09-01T15:00:00Z", "2026-09-02T16:00:00Z"
    }


async def test_cancellation_does_not_mark_booked(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    await post_calcom(client, "BOOKING_CANCELLED", booking_payload(seed))

    assert await jobs_of("hubspot_mark_booked") == []


async def test_booking_matches_prospect_by_attendee_email(
    client: httpx.AsyncClient,
):
    """No metadata (a booking made straight from the public page) still
    reaches the right prospect via the attendee address."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    await post_calcom(
        client, "BOOKING_CREATED", booking_payload(seed, metadata={})
    )

    synced = await jobs_of("hubspot_mark_booked")
    assert synced[0].payload["prospect_id"] == seed["prospect_id"]


async def test_booking_metadata_cannot_reach_another_workspace(
    client: httpx.AsyncClient,
):
    """metadata is attacker-controllable: a prospect_id from another tenant
    must not be written to."""
    seed = await seed_workspace(slug="acme")
    other = await seed_workspace(slug="other", admin_email="admin@other.test")
    await configure(seed["workspace_id"], "calcom")

    await post_calcom(
        client, "BOOKING_CREATED",
        {"uid": "bk_x", "startTime": "2026-09-01T15:00:00Z",
         "metadata": {"prospect_id": other["prospect_id"]}, "attendees": []},
    )

    synced = await jobs_of("hubspot_mark_booked")
    assert all(
        j.payload["prospect_id"] != other["prospect_id"] for j in synced
    )


async def test_booking_without_uid_is_ignored(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    resp = await post_calcom(client, "BOOKING_CREATED", {"startTime": "x"})

    assert resp.status_code == 200
    assert await jobs_of("hubspot_mark_booked") == []


async def test_replayed_booking_event_is_deduped(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    await post_calcom(client, "BOOKING_CREATED", booking_payload(seed))
    second = await post_calcom(client, "BOOKING_CREATED", booking_payload(seed))

    assert second.json() == {"received": True, "duplicate": True}
    assert len(await jobs_of("hubspot_mark_booked")) == 1


async def test_calcom_malformed_json_rejected(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "calcom")

    body = b"{broken"
    sig = hmac.new(CALCOM_SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/webhooks/acme/calcom", content=body,
        headers={"X-Cal-Signature-256": sig},
    )
    assert resp.status_code == 400


# ── Twilio Voice IVR ─────────────────────────────────────────────────

VOICE_URL = "http://testserver/webhooks/acme/voice"
GATHER_URL = "http://testserver/webhooks/acme/voice/gather"
STATUS_URL = "http://testserver/webhooks/acme/voice/status"


async def post_twiml(client: httpx.AsyncClient, path: str, url: str, form: dict):
    return await client.post(path, data=form, headers=twilio_headers(url, form))


async def test_voice_greeting_gathers_input(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice", VOICE_URL,
        {"From": "+254700000001", "CallSid": "CA1"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Gather" in resp.text
    assert "/webhooks/acme/voice/gather" in resp.text


async def test_voice_greeting_escapes_company_name(client: httpx.AsyncClient):
    """A playbook value lands inside TwiML — it must not be able to inject
    markup into the document."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.playbook = dict(ws.playbook or {}, company_name="Ben & Co <Hangup/>")

    resp = await post_twiml(
        client, "/webhooks/acme/voice", VOICE_URL, {"From": "+254700000001"}
    )

    assert "Ben &amp; Co &lt;Hangup/&gt;" in resp.text
    assert "<Hangup/>" not in resp.text


async def test_voice_unknown_workspace_returns_empty_twiml(
    client: httpx.AsyncClient,
):
    resp = await client.post("/webhooks/nosuch/voice", data={"From": "+1"})

    assert resp.status_code == 200
    assert "<Response/>" in resp.text


async def test_voice_rejects_bad_signature(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await client.post(
        "/webhooks/acme/voice", data={"From": "+254700000001"},
        headers={"X-Twilio-Signature": "wrong"},
    )
    assert resp.status_code == 401


async def test_digit_one_dials_the_sales_line(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio", sales_phone="+15551234567")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/gather", GATHER_URL,
        {"Digits": "1", "From": "+254700000001", "CallSid": "CA1"},
    )

    assert "<Dial><Number>+15551234567</Number></Dial>" in resp.text
    assert await jobs_of("voice_schedule_link") == []


async def test_digit_one_without_sales_line_falls_back_to_link(
    client: httpx.AsyncClient,
):
    """No configured sales number: the caller must still get the calendar
    link rather than a dead end."""
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/gather", GATHER_URL,
        {"Digits": "1", "From": "+254700000001", "CallSid": "CA1"},
    )

    assert "<Dial>" not in resp.text
    assert len(await jobs_of("voice_schedule_link")) == 1


async def test_digit_two_enqueues_calendar_link(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/gather", GATHER_URL,
        {"Digits": "2", "From": "+254700000001", "CallSid": "CA1"},
    )

    assert "calendar link" in resp.text
    queued = await jobs_of("voice_schedule_link")
    assert len(queued) == 1
    assert queued[0].payload["prospect_id"] == seed["prospect_id"]
    assert queued[0].idempotency_key == "voice-link:CA1"


async def test_repeated_gather_on_one_call_enqueues_one_link(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")
    form = {"Digits": "2", "From": "+254700000001", "CallSid": "CA1"}

    await post_twiml(client, "/webhooks/acme/voice/gather", GATHER_URL, form)
    await post_twiml(client, "/webhooks/acme/voice/gather", GATHER_URL, form)

    assert len(await jobs_of("voice_schedule_link")) == 1


async def test_gather_from_unknown_caller_promises_nothing(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/gather", GATHER_URL,
        {"Digits": "2", "From": "+15559999999", "CallSid": "CA1"},
    )

    assert "calendar link" not in resp.text
    assert "follow up by email" in resp.text
    assert await jobs_of("voice_schedule_link") == []


async def test_call_status_lands_on_the_prospect_timeline(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/status", STATUS_URL,
        {"CallStatus": "completed", "CallDuration": "42",
         "From": "+254700000001", "CallSid": "CA1"},
    )

    assert resp.json() == {"received": True}
    logged = await inbound_messages("voice")
    assert [m.body for m in logged] == ["Call completed (42s)"]
    assert logged[0].status == "completed"


async def test_replayed_call_status_logs_once(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")
    form = {"CallStatus": "completed", "CallDuration": "42",
            "From": "+254700000001", "CallSid": "CA1"}

    await post_twiml(client, "/webhooks/acme/voice/status", STATUS_URL, form)
    await post_twiml(client, "/webhooks/acme/voice/status", STATUS_URL, form)

    assert len(await inbound_messages("voice")) == 1


async def test_call_status_for_unknown_caller_is_accepted(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    await configure(seed["workspace_id"], "twilio")

    resp = await post_twiml(
        client, "/webhooks/acme/voice/status", STATUS_URL,
        {"CallStatus": "busy", "CallDuration": "0", "From": "+15559999999",
         "CallSid": "CA9"},
    )

    assert resp.json() == {"received": True}
    assert await inbound_messages("voice") == []


# ── Public unsubscribe ───────────────────────────────────────────────


async def unsubscribe_token(prospect_id: str) -> str:
    async with db_session() as db:
        return (await db.get(Prospect, prospect_id)).unsubscribe_token


async def test_unsubscribe_post_suppresses_every_channel(
    client: httpx.AsyncClient,
):
    """One click must stop email, SMS and WhatsApp — not just the channel
    the link happened to arrive on."""
    seed = await seed_workspace()
    token = await unsubscribe_token(seed["prospect_id"])

    resp = await client.post(f"/u/{token}")

    assert resp.status_code == 200
    assert "You're unsubscribed" in resp.text
    assert {s.channel for s in await suppressions()} == {
        "email", "sms", "whatsapp"
    }
    prospect = await get_prospect(seed["prospect_id"])
    assert prospect.stage == "opted_out"
    assert prospect.next_followup_at is None


async def test_unsubscribe_without_phone_suppresses_email_only(
    client: httpx.AsyncClient,
):
    seed = await seed_workspace()
    async with db_session() as db:
        (await db.get(Prospect, seed["prospect_id"])).phone = None
    token = await unsubscribe_token(seed["prospect_id"])

    await client.post(f"/u/{token}")

    assert {s.channel for s in await suppressions()} == {"email"}


async def test_repeated_unsubscribe_is_idempotent(client: httpx.AsyncClient):
    """Mail providers retry one-click POSTs; a second click must not error."""
    seed = await seed_workspace()
    token = await unsubscribe_token(seed["prospect_id"])

    first = await client.post(f"/u/{token}")
    second = await client.post(f"/u/{token}")

    assert first.status_code == second.status_code == 200
    assert len(await suppressions("email")) == 1


async def test_unknown_unsubscribe_token_is_404(client: httpx.AsyncClient):
    await seed_workspace()

    assert (await client.get("/u/nope")).status_code == 404
    assert (await client.post("/u/nope")).status_code == 404

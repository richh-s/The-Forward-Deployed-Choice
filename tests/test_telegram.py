"""Telegram channel: fail-closed webhook, deep-link binding, /stop
compliance, reply-agent flow, and sink-gated sends."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from engine.db import db_session
from engine.models import Draft, Job, Prospect, Workspace
from engine.queue import process_one
from engine.services.credentials import set_credentials
from engine.services.suppression import SendBlocked, is_suppressed
from tests.conftest import seed_workspace

SECRET = "tg-secret-token-for-tests"


async def _with_bot(seed) -> None:
    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "telegram", {
            "bot_token": "123:testtoken",
            "bot_username": "tenacious_test_bot",
            "operator_chat_id": "999000",
            "webhook_secret": SECRET,
        })


def _update(chat_id: str, text: str, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id},
            "text": text,
        },
    }


async def test_webhook_fails_closed(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await _with_bot(seed)
    resp = await client.post(
        f"/webhooks/{seed['slug']}/telegram", json=_update("1", "hi")
    )
    assert resp.status_code == 401  # no secret header
    resp = await client.post(
        f"/webhooks/{seed['slug']}/telegram", json=_update("1", "hi"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 401


async def test_deep_link_start_binds_chat(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await _with_bot(seed)
    resp = await client.post(
        f"/webhooks/{seed['slug']}/telegram",
        json=_update("555111", f"/start {seed['prospect_id']}"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )
    assert resp.status_code == 200 and resp.json().get("linked")
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.telegram_chat_id == "555111"
        # A welcome reply job was queued (bot utility send).
        job = (await db.execute(
            select(Job).where(Job.type == "telegram_raw_send")
        )).scalars().first()
        assert job is not None


async def test_stop_opts_out_everywhere(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await _with_bot(seed)
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.telegram_chat_id = "555222"
    resp = await client.post(
        f"/webhooks/{seed['slug']}/telegram",
        json=_update("555222", "/stop"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )
    assert resp.json().get("opted_out")
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "opted_out"
        assert await is_suppressed(
            db, seed["workspace_id"], "telegram", "555222"
        )


async def test_inbound_runs_reply_agent_and_answers_on_telegram(
    client: httpx.AsyncClient,
):
    import json as _json

    from engine.services.llm import LLMResult

    seed = await seed_workspace()
    await _with_bot(seed)
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.telegram_chat_id = "555333"
    resp = await client.post(
        f"/webhooks/{seed['slug']}/telegram",
        json=_update("555333", "What does an engagement cost?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )
    assert resp.json().get("queued")

    async def fake_complete(db, workspace_id, **kwargs):
        return LLMResult(
            text=_json.dumps({
                "intent": "question",
                "reply": "Our public bands start at $8k/mo. Send /stop to opt out.",
                "escalate": False,
                "escalation_reason": "",
            }),
            model="claude-opus-5", input_tokens=1, output_tokens=1,
        )

    with patch(
        "engine.services.llm.complete", new=AsyncMock(side_effect=fake_complete)
    ):
        assert await process_one()  # inbound_message job
    async with db_session() as db:
        draft = (await db.execute(
            select(Draft).where(Draft.kind == "reply")
        )).scalars().first()
        assert draft is not None
        assert draft.channel == "telegram"
        assert draft.status == "pending_review"  # held for approval
        assert draft.subject == ""


async def test_send_telegram_sink_reroutes_to_operator_chat():
    from engine.services.telegram import send_telegram

    seed = await seed_workspace()
    await _with_bot(seed)
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.telegram_chat_id = "555444"
        calls = []

        async def fake_tg(token, method, payload):
            calls.append(payload)
            return {"ok": True, "result": {"message_id": 42}}

        with patch(
            "engine.services.telegram._tg_call",
            new=AsyncMock(side_effect=fake_tg),
        ):
            msg = await send_telegram(
                db, ws, prospect, body="hello", is_reply=True
            )
        # Sink mode (tests run LIVE_MODE=false): delivered to the operator
        # chat, never the prospect's, with the intent noted.
        assert calls[0]["chat_id"] == "999000"
        assert "intended for chat 555444" in calls[0]["text"]
        assert msg.channel == "telegram"


async def test_send_telegram_requires_linked_chat():
    from engine.services.telegram import send_telegram

    seed = await seed_workspace()
    await _with_bot(seed)
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        with pytest.raises(SendBlocked, match="no linked Telegram chat"):
            await send_telegram(db, ws, prospect, body="hi")

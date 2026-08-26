"""Suppression list, caps, unsubscribe, and STOP handling."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from engine.db import db_session
from engine.models import Prospect, Suppression, Workspace
from engine.services.credentials import set_credentials
from engine.services.suppression import SendBlocked, check_can_send, suppress
from tests.conftest import seed_workspace


async def test_suppressed_recipient_blocks_send():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        await suppress(db, ws.id, "email", seed["prospect_email"], "opt_out")
        with pytest.raises(SendBlocked, match="suppression list"):
            await check_can_send(db, ws, "email", seed["prospect_email"])


async def test_paused_workspace_blocks_send():
    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.outbound_paused = True
        ws.pause_reason = "kill-switch"
        with pytest.raises(SendBlocked, match="paused"):
            await check_can_send(db, ws, "email", "someone@example.com")


async def test_daily_cap_enforced(monkeypatch):
    from engine import config

    seed = await seed_workspace()
    monkeypatch.setattr(
        config.get_settings(), "max_emails_per_day_per_workspace", 2
    )
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        await check_can_send(db, ws, "email", "a@example.com")
        await check_can_send(db, ws, "email", "b@example.com")
        with pytest.raises(SendBlocked, match="cap"):
            await check_can_send(db, ws, "email", "c@example.com")


async def test_unsubscribe_get_is_not_destructive(client: httpx.AsyncClient):
    """Mail scanners prefetch GETs — only the POST may unsubscribe."""
    seed = await seed_workspace()
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        token = prospect.unsubscribe_token
    resp = await client.get(f"/u/{token}")
    assert resp.status_code == 200 and "Unsubscribe" in resp.text
    async with db_session() as db:
        from sqlalchemy import select

        assert not (await db.execute(select(Suppression))).scalars().all()
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage != "opted_out"


async def test_unsubscribe_post_suppresses(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        token = prospect.unsubscribe_token
    resp = await client.post(f"/u/{token}")  # RFC 8058 one-click / form POST
    assert resp.status_code == 200 and "unsubscribed" in resp.text
    async with db_session() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(Suppression))).scalars().all()
        assert {(s.channel) for s in rows} == {"email", "sms"}
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "opted_out"


async def test_sms_stop_suppresses_and_confirms(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "africastalking",
            {"username": "sandbox", "api_key": "atsk", "webhook_token": "tok"},
        )
    sent = []

    async def fake_at_send(username, api_key, to, body, sender_id):
        sent.append((to, body))
        return {
            "SMSMessageData": {
                "Recipients": [{"status": "Success", "messageId": "at_1"}]
            }
        }

    with patch("engine.services.smser._at_send", new=AsyncMock(side_effect=fake_at_send)):
        resp = await client.post(
            "/webhooks/acme/sms/tok",
            data={"text": "STOP", "from": "+254700000001", "id": "evt1"},
        )
    assert resp.json()["status"] == "opted_out"
    assert sent and "unsubscribed" in sent[0][1]
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "opted_out"
        ws = await db.get(Workspace, seed["workspace_id"])
        from engine.services.suppression import is_suppressed

        assert await is_suppressed(db, ws.id, "sms", "+254700000001")

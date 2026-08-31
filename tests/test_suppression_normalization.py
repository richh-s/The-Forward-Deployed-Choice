"""Suppression addresses are normalised per channel.

Telegram's address is a numeric chat id, not a phone number. It used to be run
through normalize_phone, which prepended a '+' ("555" -> "+555"). Reads
normalised the same way so opt-outs worked, but the stored value was wrong and
any lookup bypassing this module would miss it.
"""
import pytest

from engine.db import db_session
from engine.models import Suppression
from engine.services.suppression import (
    PHONE_CHANNELS,
    is_suppressed,
    normalize_address,
    suppress,
    unsuppress,
)
from tests.conftest import seed_workspace


@pytest.mark.parametrize(
    "channel,raw,expected",
    [
        ("email", "  Jane@Example.COM ", "jane@example.com"),
        ("sms", "254700000001", "+254700000001"),
        ("sms", "+254 700-000 001", "+254700000001"),
        ("whatsapp", "254700000001", "+254700000001"),
        ("voice", "254700000001", "+254700000001"),
        # The regression: a chat id must not acquire a phone's "+".
        ("telegram", "555", "555"),
        ("telegram", " 1220506887 ", "1220506887"),
        # Telegram group chats are negative and were never "+"-prefixed.
        ("telegram", "-1001234567", "-1001234567"),
    ],
)
def test_normalize_address_by_channel(channel, raw, expected):
    assert normalize_address(channel, raw) == expected


def test_phone_channels_are_explicit():
    assert PHONE_CHANNELS == frozenset({"sms", "whatsapp", "voice"})
    assert "telegram" not in PHONE_CHANNELS
    assert "email" not in PHONE_CHANNELS


async def test_telegram_chat_id_is_stored_verbatim():
    seed = await seed_workspace()
    async with db_session() as db:
        await suppress(db, seed["workspace_id"], "telegram", "555", "opt_out")
    async with db_session() as db:
        rows = list((await db.execute(
            __import__("sqlalchemy").select(Suppression)
        )).scalars().all())
    assert [(r.channel, r.address) for r in rows] == [("telegram", "555")]


async def test_telegram_opt_out_round_trips():
    seed = await seed_workspace()
    async with db_session() as db:
        await suppress(db, seed["workspace_id"], "telegram", "1220506887", "opt_out")
    async with db_session() as db:
        assert await is_suppressed(db, seed["workspace_id"], "telegram", "1220506887")
        # whitespace variants still match
        assert await is_suppressed(db, seed["workspace_id"], "telegram", " 1220506887 ")
        assert not await is_suppressed(db, seed["workspace_id"], "telegram", "999")


async def test_unsuppress_matches_the_stored_form():
    seed = await seed_workspace()
    async with db_session() as db:
        await suppress(db, seed["workspace_id"], "telegram", "555", "opt_out")
    async with db_session() as db:
        await unsuppress(db, seed["workspace_id"], "telegram", "555")
    async with db_session() as db:
        assert not await is_suppressed(db, seed["workspace_id"], "telegram", "555")


async def test_phone_opt_out_still_normalises():
    """The phone channels must keep their E.164 canonicalisation."""
    seed = await seed_workspace()
    async with db_session() as db:
        await suppress(db, seed["workspace_id"], "sms", "254700000001", "opt_out")
    async with db_session() as db:
        # stored with "+", so the "+"-less form must still match
        assert await is_suppressed(db, seed["workspace_id"], "sms", "+254700000001")
        assert await is_suppressed(db, seed["workspace_id"], "sms", "254700000001")

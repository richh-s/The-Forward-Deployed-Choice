"""Identity-linked Anthropic keys must declare a workspace id.

Without the `anthropic-workspace-id` header such a key is rejected with a 400
on every call. Ordinary keys must be unaffected — the header is only sent when
one is configured.
"""
import anthropic
import pytest

from engine.db import db_session
from engine.services import llm
from engine.services.credentials import set_credentials
from tests.conftest import seed_workspace


@pytest.fixture(autouse=True)
def clear_client_cache():
    llm._anthropic_clients.clear()
    yield
    llm._anthropic_clients.clear()


def header_of(client: anthropic.AsyncAnthropic) -> str | None:
    for k, v in client.default_headers.items():
        if k.lower() == "anthropic-workspace-id":
            return v
    return None


async def test_no_header_for_an_ordinary_key(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "anthropic_workspace_id", "", raising=False)
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "anthropic", {"api_key": "sk-a"})
    async with db_session() as db:
        client = await llm._client_for_workspace(db, seed["workspace_id"])
    assert header_of(client) is None


async def test_workspace_credential_supplies_the_header():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "anthropic",
            {"api_key": "sk-a", "workspace_id": "wrkspc_tenant"},
        )
    async with db_session() as db:
        client = await llm._client_for_workspace(db, seed["workspace_id"])
    assert header_of(client) == "wrkspc_tenant"


async def test_platform_setting_is_the_fallback(monkeypatch):
    monkeypatch.setattr(
        llm.get_settings(), "anthropic_workspace_id", "wrkspc_platform",
        raising=False,
    )
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(db, seed["workspace_id"], "anthropic", {"api_key": "sk-a"})
    async with db_session() as db:
        client = await llm._client_for_workspace(db, seed["workspace_id"])
    assert header_of(client) == "wrkspc_platform"


async def test_same_key_different_workspaces_get_separate_clients():
    """Two tenants may share an API key but act in different Anthropic
    workspaces — reusing one cached client would send the wrong header."""
    a = await seed_workspace(slug="a")
    b = await seed_workspace(slug="b", admin_email="admin@b.test")
    async with db_session() as db:
        await set_credentials(
            db, a["workspace_id"], "anthropic",
            {"api_key": "shared-key", "workspace_id": "wrkspc_a"},
        )
        await set_credentials(
            db, b["workspace_id"], "anthropic",
            {"api_key": "shared-key", "workspace_id": "wrkspc_b"},
        )
    async with db_session() as db:
        ca = await llm._client_for_workspace(db, a["workspace_id"])
        cb = await llm._client_for_workspace(db, b["workspace_id"])
    assert header_of(ca) == "wrkspc_a"
    assert header_of(cb) == "wrkspc_b"
    assert ca is not cb


async def test_workspace_id_is_an_accepted_credential_field():
    from engine.services.credentials import validate_credential_payload
    cleaned = validate_credential_payload(
        "anthropic", {"api_key": "sk-a", "workspace_id": "wrkspc_x"}
    )
    assert cleaned == {"api_key": "sk-a", "workspace_id": "wrkspc_x"}

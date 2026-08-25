"""Local (OpenAI-compatible) LLM backend: routing, JSON handling, cost."""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from engine.services import llm

SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}, "score": {"type": "number"}},
    "required": ["verdict", "score"],
    "additionalProperties": False,
}


def _resp(status: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=body,
        request=httpx.Request("POST", "http://gpu.test/v1/chat/completions"),
    )


def _chat_body(content: str, prompt_tokens: int = 100) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 50},
    }


@pytest.fixture(autouse=True)
def local_base_url(monkeypatch):
    from engine.config import get_settings

    monkeypatch.setattr(get_settings(), "local_llm_base_url", "http://gpu.test/v1")


async def test_local_prefix_routes_to_local_backend():
    calls = []

    async def fake_chat(base_url, api_key, payload):
        calls.append((base_url, payload))
        return _resp(200, _chat_body(json.dumps({"verdict": "ok", "score": 0.9})))

    with patch("engine.services.llm._local_chat", new=AsyncMock(side_effect=fake_chat)):
        result = await llm.complete(
            None, "ws1", model="local:qwen2.5:7b", system="You judge.",
            messages=[{"role": "user", "content": "judge this"}],
            json_schema=SCHEMA,
        )
    assert result.json() == {"verdict": "ok", "score": 0.9}
    assert result.cost_usd == 0.0
    base_url, payload = calls[0]
    assert base_url == "http://gpu.test/v1"
    assert payload["model"] == "qwen2.5:7b"  # prefix stripped
    assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
    # JSON-only instruction baked into the system prompt as a fallback.
    assert "ONLY a JSON object" in payload["messages"][0]["content"]


async def test_code_fenced_output_is_parsed():
    fenced = "```json\n" + json.dumps({"verdict": "ok", "score": 1.0}) + "\n```"
    with patch(
        "engine.services.llm._local_chat",
        new=AsyncMock(return_value=_resp(200, _chat_body(fenced))),
    ):
        result = await llm.complete(
            None, "ws1", model="local:m", system="s",
            messages=[{"role": "user", "content": "u"}], json_schema=SCHEMA,
        )
    assert result.json()["score"] == 1.0


async def test_response_format_rejection_falls_back():
    responses = [
        _resp(400, {"error": "response_format unsupported"}),
        _resp(200, _chat_body(json.dumps({"verdict": "ok", "score": 0.5}))),
    ]
    calls = []

    async def fake_chat(base_url, api_key, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch("engine.services.llm._local_chat", new=AsyncMock(side_effect=fake_chat)):
        result = await llm.complete(
            None, "ws1", model="local:m", system="s",
            messages=[{"role": "user", "content": "u"}], json_schema=SCHEMA,
        )
    assert result.json()["verdict"] == "ok"
    assert "response_format" in calls[0] and "response_format" not in calls[1]


async def test_corrective_retry_on_missing_keys():
    responses = [
        _resp(200, _chat_body("Sure! The verdict is ok.")),  # not JSON
        _resp(200, _chat_body(json.dumps({"verdict": "ok", "score": 0.7}))),
    ]
    calls = []

    async def fake_chat(base_url, api_key, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch("engine.services.llm._local_chat", new=AsyncMock(side_effect=fake_chat)):
        result = await llm.complete(
            None, "ws1", model="local:m", system="s",
            messages=[{"role": "user", "content": "u"}], json_schema=SCHEMA,
        )
    assert result.json()["score"] == 0.7
    # The corrective turn includes the bad answer and the schema.
    corrective = calls[1]["messages"]
    assert corrective[-2]["role"] == "assistant"
    assert "schema" in corrective[-1]["content"]


async def test_persistent_bad_output_raises():
    bad = _resp(200, _chat_body("still not json"))
    with patch("engine.services.llm._local_chat", new=AsyncMock(return_value=bad)):
        with pytest.raises(RuntimeError, match="missing required keys|Local model"):
            await llm.complete(
                None, "ws1", model="local:m", system="s",
                messages=[{"role": "user", "content": "u"}], json_schema=SCHEMA,
            )


async def test_unconfigured_base_url_errors(monkeypatch):
    from engine.config import get_settings

    monkeypatch.setattr(get_settings(), "local_llm_base_url", "")
    with pytest.raises(RuntimeError, match="LOCAL_LLM_BASE_URL"):
        await llm.complete(
            None, "ws1", model="local:m", system="s",
            messages=[{"role": "user", "content": "u"}],
        )


def test_extract_json_variants():
    assert llm.extract_json('{"a": 1}') == {"a": 1}
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('Here you go: {"a": 1}') == {"a": 1}
    with pytest.raises(ValueError):
        llm.extract_json("no json here")


async def test_model_for_resolves_workspace_override_then_default():
    from engine.config import get_settings
    from engine.services.llm import model_for

    defaults = get_settings()
    ws_default = type("W", (), {"llm_config": {}})()
    assert model_for(ws_default, "judge") == defaults.judge_model
    assert model_for(ws_default, "compose") == defaults.compose_model

    ws_local = type("W", (), {"llm_config": {"judge": "local:gemma-4-26b"}})()
    assert model_for(ws_local, "judge") == "local:gemma-4-26b"
    # unset roles still fall back to the platform default
    assert model_for(ws_local, "reply") == defaults.reply_model


async def test_settings_models_route_persists_config(client):
    from engine.db import db_session
    from engine.models import Workspace
    from tests.conftest import login, seed_workspace

    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await client.post(
        "/settings/models",
        data={"judge_model": "local:gemma-4-26b", "compose_model": "", "reply_model": ""},
    )
    assert resp.status_code == 303
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        assert ws.llm_config == {"judge": "local:gemma-4-26b"}

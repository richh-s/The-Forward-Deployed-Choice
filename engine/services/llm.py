"""LLM access — Claude API plus self-hosted local models.

One choke point for every model call. Two backends:

- Anthropic (default): per-workspace API key falling back to the platform
  key; JSON-schema-constrained outputs via output_config.
- Local (OpenAI-compatible): any model string prefixed with ``local:`` is
  served from LOCAL_LLM_BASE_URL (Ollama / LM Studio / vLLM / llama.cpp —
  all expose /v1/chat/completions). Typical setup: the judge runs on a
  tailnet-hosted model (JUDGE_MODEL=local:<name>) while customer-facing
  compose/reply stay on Claude. Local calls cost $0 and never leave the
  private network.

Structured output: Anthropic enforces the schema server-side. Local servers
vary — we request OpenAI-style ``response_format`` json_schema, retry without
it if the server rejects the parameter, and validate required keys ourselves
(one corrective retry) so callers can rely on .json() either way.
"""
import json
import logging
import re

import anthropic
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from engine.config import get_settings
from engine.queue import PermanentJobError
from engine.services.credentials import get_credentials

logger = logging.getLogger(__name__)

LOCAL_PREFIX = "local:"

_local_client: httpx.AsyncClient | None = None
_warned_plaintext_key = False


class LLMPermanentError(PermanentJobError):
    """A model outcome that will repeat on an identical retry (refusal,
    output truncated at the configured max_tokens). Jobs hitting this go
    straight to dead instead of re-billing the same prompt five times."""


def _get_local_client() -> httpx.AsyncClient:
    """Long-timeout pooled client for the local backend (reasoning models
    are slow; don't pay a TLS/TCP handshake per call on top)."""
    global _local_client, _warned_plaintext_key
    settings = get_settings()
    if (
        not _warned_plaintext_key
        and settings.local_llm_api_key
        and settings.local_llm_base_url.startswith("http://")
    ):
        logger.warning(
            "LOCAL_LLM_API_KEY is sent as a bearer token over plaintext "
            "http:// — acceptable only on a private network/tailnet"
        )
        _warned_plaintext_key = True
    if _local_client is None or _local_client.is_closed:
        _local_client = httpx.AsyncClient(
            timeout=settings.local_llm_timeout_seconds,
            follow_redirects=False,
        )
    return _local_client

# USD per 1M tokens (input, output). Claude API first-party rates.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_PRICING = (5.00, 25.00)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model.startswith(LOCAL_PREFIX):
        return 0.0
    for prefix, (inp, outp) in PRICING.items():
        if model.startswith(prefix):
            return input_tokens * inp / 1e6 + output_tokens * outp / 1e6
    inp, outp = _DEFAULT_PRICING
    return input_tokens * inp / 1e6 + output_tokens * outp / 1e6


def model_for(workspace, role: str) -> str:
    """Resolve the model for a pipeline role ("compose" | "reply" | "judge").

    A per-workspace override (Settings → Models) wins over the platform env
    default, so one deployment can run e.g. a local judge for tenant A and a
    Claude judge for tenant B. A `local:` prefix routes to LOCAL_LLM_BASE_URL.
    """
    settings = get_settings()
    default = {
        "compose": settings.compose_model,
        "reply": settings.reply_model,
        "judge": settings.judge_model,
    }[role]
    override = (getattr(workspace, "llm_config", None) or {}).get(role)
    return override or default


class LLMResult:
    def __init__(self, text: str, model: str, input_tokens: int, output_tokens: int):
        self.text = text
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd(model, input_tokens, output_tokens)

    def json(self) -> dict:
        return json.loads(self.text)


# ── Anthropic backend ────────────────────────────────────────────────


# One long-lived client (and connection pool) per distinct API key, instead
# of a new client per call — a per-call client leaks connections/FDs on a
# long-lived worker. Bounded: evicting the oldest closes its pool.
_anthropic_clients: dict[str, anthropic.AsyncAnthropic] = {}
_MAX_ANTHROPIC_CLIENTS = 32


async def _client_for_workspace(
    db: AsyncSession, workspace_id: str
) -> anthropic.AsyncAnthropic:
    settings = get_settings()
    creds = await get_credentials(db, workspace_id, "anthropic")
    api_key = (creds or {}).get("api_key") or settings.anthropic_api_key
    if not api_key:
        raise RuntimeError(
            "No Anthropic API key configured (workspace credentials or "
            "ANTHROPIC_API_KEY)"
        )
    client = _anthropic_clients.get(api_key)
    if client is None:
        while len(_anthropic_clients) >= _MAX_ANTHROPIC_CLIENTS:
            oldest_key = next(iter(_anthropic_clients))
            oldest = _anthropic_clients.pop(oldest_key)
            try:
                await oldest.close()
            except Exception:  # noqa: BLE001 — eviction is best-effort
                pass
        client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        _anthropic_clients[api_key] = client
    return client


async def _complete_anthropic(
    db: AsyncSession,
    workspace_id: str,
    *,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
    effort: str | None,
    json_schema: dict | None,
) -> LLMResult:
    client = await _client_for_workspace(db, workspace_id)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    output_config: dict = {}
    if effort:
        output_config["effort"] = effort
    if json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    if output_config:
        kwargs["output_config"] = output_config

    response = await client.messages.create(**kwargs)

    # Deterministic outcomes: the same prompt will refuse/truncate again, so
    # these are permanent — the queue must not spend retries (and money) on them.
    if response.stop_reason == "refusal":
        detail = ""
        if getattr(response, "stop_details", None):
            detail = f" ({response.stop_details.explanation})"
        raise LLMPermanentError(f"Model declined the request{detail}")
    if response.stop_reason == "max_tokens":
        raise LLMPermanentError(
            "Model output truncated at max_tokens; raise the limit"
        )

    text = "".join(b.text for b in response.content if b.type == "text")
    return LLMResult(
        text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


# ── Local (OpenAI-compatible) backend ────────────────────────────────


def _is_retryable_http(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


@retry(
    retry=retry_if_exception(_is_retryable_http),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=15),
    reraise=True,
)
async def _local_chat(base_url: str, api_key: str, payload: dict) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return await _get_local_client().post(
        f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload
    )


# Reasoning models (e.g. gemma via Ollama) sometimes leak their internal
# channel markers into the text stream; strip them before JSON extraction.
_CHANNEL_RE = re.compile(r"<\|?channel\|?>[^\n`{]*", re.IGNORECASE)


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(text: str) -> dict:
    """Parse a JSON object from local-model output, tolerating code fences
    and leading prose."""
    text = _CHANNEL_RE.sub("", text).strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _missing_keys(obj: dict, json_schema: dict) -> list[str]:
    return [k for k in json_schema.get("required", []) if k not in obj]


async def _complete_local(
    *,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
    json_schema: dict | None,
) -> LLMResult:
    settings = get_settings()
    if not settings.local_llm_base_url:
        raise RuntimeError(
            f"Model {model!r} routes to the local backend but "
            "LOCAL_LLM_BASE_URL is not configured"
        )
    model_name = model.removeprefix(LOCAL_PREFIX)
    # Local models are often reasoning models that spend the token budget
    # thinking before emitting the answer, so give them ample headroom —
    # otherwise the response is truncated with empty content.
    max_tokens = max(max_tokens, settings.local_llm_min_max_tokens)
    if json_schema is not None:
        # Belt and braces: some servers ignore response_format entirely, so
        # the instruction also lives in the system prompt.
        system = (
            f"{system}\n\nRespond with ONLY a JSON object matching this "
            f"schema — no prose, no code fences:\n{json.dumps(json_schema)}"
        )
    chat_messages = [{"role": "system", "content": system}, *messages]

    async def _call(msgs: list[dict], use_response_format: bool) -> httpx.Response:
        payload: dict = {
            "model": model_name,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_schema is not None and use_response_format:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema, "strict": True},
            }
        return await _local_chat(
            settings.local_llm_base_url, settings.local_llm_api_key, payload
        )

    resp = await _call(chat_messages, use_response_format=True)
    if resp.status_code == 400 and json_schema is not None:
        # Older servers reject response_format — fall back to prompt-only JSON.
        logger.info("Local LLM rejected response_format; retrying without it")
        resp = await _call(chat_messages, use_response_format=False)
    resp.raise_for_status()
    body = resp.json()

    def _parse(b: dict) -> tuple[str, dict]:
        choices = b.get("choices") or []
        if not choices:
            raise RuntimeError(f"Local LLM returned no choices: {str(b)[:200]}")
        msg = choices[0].get("message", {})
        # Reasoning models sometimes leave content empty and put everything in
        # a separate reasoning field (esp. when truncated) — fall back to it.
        content = msg.get("content") or msg.get("reasoning") or ""
        return content, b.get("usage") or {}

    text, usage = _parse(body)

    if json_schema is not None:
        try:
            obj = extract_json(text)
            missing = _missing_keys(obj, json_schema)
        except ValueError:
            obj, missing = None, ["<unparseable>"]
        if missing:
            # One corrective retry naming what was wrong.
            fix_msgs = chat_messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was not valid for the required JSON "
                        f"schema (missing/invalid: {', '.join(missing)}). Respond "
                        "again with ONLY a JSON object matching this schema, no "
                        f"prose, no code fences:\n{json.dumps(json_schema)}"
                    ),
                },
            ]
            resp = await _call(fix_msgs, use_response_format=False)
            resp.raise_for_status()
            text, usage = _parse(resp.json())
            try:
                obj = extract_json(text)
                missing = _missing_keys(obj, json_schema)
            except ValueError as exc:
                raise RuntimeError(
                    "Local model failed to produce parseable JSON after retry"
                ) from exc
            if missing:
                raise RuntimeError(
                    f"Local model output missing required keys after retry: {missing}"
                )
        text = json.dumps(obj)

    return LLMResult(
        text=text,
        model=model,
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
    )


# ── public entry point ───────────────────────────────────────────────


async def complete(
    db: AsyncSession,
    workspace_id: str,
    *,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int = 2048,
    effort: str | None = None,
    json_schema: dict | None = None,
) -> LLMResult:
    """Run one model call. With json_schema, .json() is guaranteed to parse
    and contain the schema's required keys (both backends)."""
    if model.startswith(LOCAL_PREFIX):
        return await _complete_local(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            json_schema=json_schema,
        )
    return await _complete_anthropic(
        db,
        workspace_id,
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        effort=effort,
        json_schema=json_schema,
    )

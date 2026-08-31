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
# long-lived worker. Bounded LRU: least-recently-used key is evicted; the
# evicted client is NOT closed explicitly (a concurrent job may be
# mid-request on its pool) — dropping the reference lets GC reclaim it once
# in-flight requests finish.
from collections import OrderedDict  # noqa: E402

_anthropic_clients: OrderedDict[str, anthropic.AsyncAnthropic] = OrderedDict()
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
    # Identity-linked keys must declare which Anthropic workspace the request
    # acts in, or the API rejects every call with 400 "anthropic-workspace-id
    # is required". Ordinary keys ignore the header, so sending it when
    # configured is safe for both kinds.
    ws_id = (creds or {}).get("workspace_id") or settings.anthropic_workspace_id
    # Cache per (key, workspace) — two tenants may share a key but act in
    # different Anthropic workspaces, and reusing one client would send the
    # wrong header.
    cache_key = f"{api_key}\x00{ws_id}"
    client = _anthropic_clients.get(cache_key)
    if client is not None:
        _anthropic_clients.move_to_end(cache_key)
        return client
    while len(_anthropic_clients) >= _MAX_ANTHROPIC_CLIENTS:
        _anthropic_clients.popitem(last=False)
    client = anthropic.AsyncAnthropic(
        api_key=api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        default_headers=(
            {"anthropic-workspace-id": ws_id} if ws_id else None
        ),
    )
    _anthropic_clients[cache_key] = client
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
    # The credential lookup above opened a fresh transaction on this session.
    # Release it before the (potentially minutes-long) network call — job
    # handlers commit before calling in precisely so no DB connection sits
    # idle-in-transaction under the model call.
    await db.commit()
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
        explanation = getattr(
            getattr(response, "stop_details", None), "explanation", ""
        )
        detail = f" ({explanation})" if explanation else ""
        raise LLMPermanentError(f"Model declined the request{detail}")
    if response.stop_reason == "max_tokens":
        raise LLMPermanentError(
            "Model output truncated at max_tokens; raise the limit"
        )

    text = "".join(b.text for b in response.content if b.type == "text")
    if json_schema is not None:
        # complete() promises callers that .json() parses and carries the
        # required keys — enforce it here too, not only on the local path.
        if not text.strip():
            raise LLMPermanentError(
                f"Model returned no text content (stop_reason="
                f"{response.stop_reason})"
            )
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise LLMPermanentError(
                f"Schema-constrained output did not parse as JSON: {text[:200]}"
            ) from exc
        if not isinstance(obj, dict):
            raise LLMPermanentError(
                f"Schema-constrained output is not a JSON object: {text[:200]}"
            )
        missing = _missing_keys(obj, json_schema)
        if missing:
            raise LLMPermanentError(
                f"Schema-constrained output missing required keys: {missing}"
            )
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
    resp = await _get_local_client().post(
        f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload
    )
    # Raise retryable statuses HERE, inside the retried function — the retry
    # predicate only sees exceptions, so returning a 503 untouched would
    # make the whole 429/5xx retry branch unreachable. Other 4xx (e.g. the
    # 400 that signals response_format is unsupported) are returned for the
    # caller to inspect.
    if resp.status_code == 429 or resp.status_code >= 500:
        resp.raise_for_status()
    return resp


# Reasoning models (e.g. gemma via Ollama) sometimes leak their internal
# channel markers into the text stream; strip them before JSON extraction.
_CHANNEL_RE = re.compile(r"<\|?channel\|?>[^\n`{]*", re.IGNORECASE)


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(text: str) -> dict:
    """Parse a JSON object from local-model output, tolerating code fences
    and leading prose. Raises ValueError unless the result is a dict — a
    bare `42` or a list would otherwise slip through and crash callers that
    index into the result."""
    text = _CHANNEL_RE.sub("", text).strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        obj = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            obj = json.loads(text[start:end + 1])
        else:
            raise
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a JSON object, got {type(obj).__name__}")
    return obj


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
        if not content and choices[0].get("finish_reason") == "length":
            # Truncated with nothing usable — the same prompt truncates the
            # same way on every retry.
            raise LLMPermanentError(
                "Local model output truncated at max_tokens with no content; "
                "raise LOCAL_LLM_MIN_MAX_TOKENS"
            )
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
                # Two failures on the same prompt — a third identical call
                # is billable determinism, not a retry strategy.
                raise LLMPermanentError(
                    "Local model failed to produce parseable JSON after retry"
                ) from exc
            if missing:
                raise LLMPermanentError(
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
        # Callers may have read (e.g. conversation history) on this session —
        # release the transaction before the slow local-model call. (db may
        # be None in direct/offline use: the local path needs no DB.)
        if db is not None:
            await db.commit()
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

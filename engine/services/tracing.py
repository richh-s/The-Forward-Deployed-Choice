"""LLM tracing via Langfuse.

The engine already accounts for spend — every call's tokens and USD cost are
computed in llm.py and persisted to Draft.compose_cost_usd / Message.cost_usd,
and the kill-switch enforces a ceiling from those sums. What this adds is the
part that accounting cannot answer: *what was actually said*. When a draft
goes out badly worded, this is how you read the prompt that produced it.

Two rules govern everything here:

1. **Opt-in.** With LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY unset the whole
   module is inert, so local runs and CI behave exactly as before.
2. **Fail-open, always.** Observability is not allowed to break the product.
   A Langfuse outage, a bad key, a missing package, an SDK exception — every
   one of them degrades to "no trace" and the send proceeds. Nothing in this
   file may ever raise into a caller.

PRIVACY: traces carry full prompt and response bodies, which for this system
means prospect names, companies, email addresses and message content. Against
Langfuse Cloud that data leaves your infrastructure. Point LANGFUSE_HOST at a
self-hosted instance if that is not acceptable.
"""
import logging
from contextlib import contextmanager
from typing import Any

from engine.config import get_settings

logger = logging.getLogger(__name__)

_client: Any = None
_init_attempted = False
# One warning per process, not one per model call — a broken Langfuse config
# must not drown the logs that matter during an incident.
_warned = False


def _warn_once(message: str, *args) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning(message, *args)


def init_tracing() -> None:
    """Create the Langfuse client if it is configured. Safe to call twice."""
    global _client, _init_attempted
    if _init_attempted:
        return
    _init_attempted = True
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    try:
        from langfuse import Langfuse
    except ImportError:
        _warn_once(
            "LANGFUSE keys are set but the langfuse package is not "
            "installed; LLM tracing disabled"
        )
        return
    try:
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            environment=settings.environment,
            sample_rate=settings.langfuse_sample_rate,
            # Never let the exporter hold a shutdown open for long.
            timeout=settings.langfuse_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — see rule 2
        _warn_once("Langfuse init failed (%s); LLM tracing disabled", exc)
        return
    logger.info("LLM tracing enabled | host=%s", settings.langfuse_host)


def tracing_enabled() -> bool:
    return _client is not None


class _Span:
    """Handle returned by trace_generation(). Every method is a no-op when
    tracing is off, so callers need no conditionals."""

    __slots__ = ("_observation",)

    def __init__(self, observation: Any = None):
        self._observation = observation

    def record(self, result: Any) -> None:
        """Attach the completion and its usage to the span."""
        if self._observation is None:
            return
        try:
            self._observation.update(
                output=result.text,
                model=result.model,
                usage_details={
                    "input": result.input_tokens,
                    "output": result.output_tokens,
                },
                # The engine's own cost figure, not Langfuse's table — so the
                # dashboard reconciles with the kill-switch ledger instead of
                # quietly disagreeing with it.
                cost_details={"total": result.cost_usd},
            )
        except Exception as exc:  # noqa: BLE001
            _warn_once("Langfuse record failed (%s)", exc)


@contextmanager
def trace_generation(
    *,
    name: str,
    model: str,
    system: str,
    messages: list[dict],
    metadata: dict | None = None,
):
    """Trace one model call. Yields a _Span; call .record(result) on success.

    Errors are attached to the span and re-raised — the caller's behaviour is
    unchanged whether tracing is on or off.
    """
    if _client is None:
        yield _Span()
        return

    observation = None
    try:
        observation = _client.start_observation(
            name=name,
            as_type="generation",
            model=model,
            input={"system": system, "messages": messages},
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        _warn_once("Langfuse span start failed (%s)", exc)

    span = _Span(observation)
    try:
        yield span
    except Exception as exc:
        if observation is not None:
            try:
                observation.update(level="ERROR", status_message=str(exc)[:500])
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        if observation is not None:
            try:
                observation.end()
            except Exception as exc:  # noqa: BLE001
                _warn_once("Langfuse span end failed (%s)", exc)


def shutdown_tracing() -> None:
    """Flush buffered traces. Called on worker/web shutdown; never raises."""
    global _client
    if _client is None:
        return
    try:
        _client.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse shutdown failed (%s)", exc)
    finally:
        _client = None


def _reset_for_tests() -> None:
    """Drop client and one-shot latches so a test can configure its own."""
    global _client, _init_attempted, _warned
    _client = None
    _init_attempted = False
    _warned = False

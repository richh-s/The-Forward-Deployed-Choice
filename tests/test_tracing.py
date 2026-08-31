"""LLM tracing is optional and fail-open.

The contract these lock down: with Langfuse unconfigured the engine behaves
exactly as before, and with Langfuse configured *but broken* it still behaves
exactly as before. Observability must never be able to break a send.
"""
import pytest

from engine.services import tracing
from engine.services.llm import LLMResult


@pytest.fixture(autouse=True)
def reset_tracing():
    tracing._reset_for_tests()
    yield
    tracing._reset_for_tests()


def result() -> LLMResult:
    return LLMResult(
        text='{"ok": true}', model="claude-opus-5",
        input_tokens=100, output_tokens=20,
    )


class FakeObservation:
    def __init__(self, recorder: dict):
        self.recorder = recorder

    def update(self, **kw):
        self.recorder.setdefault("updates", []).append(kw)

    def end(self):
        self.recorder["ended"] = True


class FakeClient:
    """Stands in for the Langfuse SDK."""

    def __init__(self):
        self.calls: dict = {}

    def start_observation(self, **kw):
        self.calls["start"] = kw
        return FakeObservation(self.calls)

    def shutdown(self):
        self.calls["shutdown"] = True


# ── disabled by default ──────────────────────────────────────────────


def test_tracing_is_off_without_keys():
    tracing.init_tracing()
    assert tracing.tracing_enabled() is False


def test_span_is_a_noop_when_disabled():
    tracing.init_tracing()
    with tracing.trace_generation(
        name="compose", model="claude-opus-5", system="s", messages=[]
    ) as span:
        span.record(result())  # must not raise


def test_shutdown_without_a_client_is_safe():
    tracing.shutdown_tracing()


# ── enabled: records what the dashboard needs ────────────────────────


def test_generation_records_prompt_usage_and_cost(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(tracing, "_client", fake)

    res = result()
    with tracing.trace_generation(
        name="compose",
        model="claude-opus-5",
        system="You are a writer",
        messages=[{"role": "user", "content": "hi"}],
        metadata={"role": "compose", "prospect_id": "p1"},
    ) as span:
        span.record(res)

    start = fake.calls["start"]
    assert start["name"] == "compose"
    assert start["as_type"] == "generation"
    assert start["input"]["system"] == "You are a writer"
    assert start["metadata"]["prospect_id"] == "p1"

    update = fake.calls["updates"][0]
    assert update["output"] == res.text
    assert update["usage_details"] == {"input": 100, "output": 20}
    # The engine's own cost figure, so Langfuse reconciles with the
    # kill-switch ledger rather than disagreeing with it.
    assert update["cost_details"] == {"total": res.cost_usd}
    assert fake.calls["ended"] is True


def test_exception_is_recorded_and_still_propagates(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(tracing, "_client", fake)

    with pytest.raises(ValueError, match="model exploded"):
        with tracing.trace_generation(
            name="judge", model="m", system="s", messages=[]
        ):
            raise ValueError("model exploded")

    assert fake.calls["updates"][0]["level"] == "ERROR"
    assert "model exploded" in fake.calls["updates"][0]["status_message"]
    assert fake.calls["ended"] is True


# ── fail-open: a broken Langfuse must not break the product ──────────


def test_span_start_failure_does_not_break_the_call(monkeypatch):
    class Exploding:
        def start_observation(self, **kw):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "_client", Exploding())

    with tracing.trace_generation(
        name="compose", model="m", system="s", messages=[]
    ) as span:
        span.record(result())  # must not raise


def test_record_failure_does_not_break_the_call(monkeypatch):
    class BadObservation:
        def update(self, **kw):
            raise RuntimeError("ingest rejected")

        def end(self):
            pass

    class Client:
        def start_observation(self, **kw):
            return BadObservation()

    monkeypatch.setattr(tracing, "_client", Client())

    with tracing.trace_generation(
        name="compose", model="m", system="s", messages=[]
    ) as span:
        span.record(result())  # must not raise


def test_end_failure_does_not_break_the_call(monkeypatch):
    class BadObservation:
        def update(self, **kw):
            pass

        def end(self):
            raise RuntimeError("flush failed")

    class Client:
        def start_observation(self, **kw):
            return BadObservation()

    monkeypatch.setattr(tracing, "_client", Client())

    with tracing.trace_generation(
        name="compose", model="m", system="s", messages=[]
    ) as span:
        span.record(result())


def test_caller_exception_survives_a_broken_tracer(monkeypatch):
    """The real failure mode: the model errored AND Langfuse is down. The
    caller must still see the model's error, not the tracer's."""
    class BadObservation:
        def update(self, **kw):
            raise RuntimeError("tracer also broken")

        def end(self):
            raise RuntimeError("and its end failed")

    class Client:
        def start_observation(self, **kw):
            return BadObservation()

    monkeypatch.setattr(tracing, "_client", Client())

    with pytest.raises(ValueError, match="the real error"):
        with tracing.trace_generation(
            name="compose", model="m", system="s", messages=[]
        ):
            raise ValueError("the real error")


def test_shutdown_failure_is_swallowed(monkeypatch):
    class Client:
        def shutdown(self):
            raise RuntimeError("network gone")

    monkeypatch.setattr(tracing, "_client", Client())
    tracing.shutdown_tracing()
    assert tracing.tracing_enabled() is False


def test_missing_package_disables_tracing(monkeypatch):
    """Keys set but langfuse not installed → disabled, not a crash."""
    import builtins

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    from engine.config import get_settings
    get_settings.cache_clear()

    real_import = builtins.__import__

    def no_langfuse(name, *a, **kw):
        if name == "langfuse":
            raise ImportError("no langfuse")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_langfuse)
    try:
        tracing.init_tracing()
        assert tracing.tracing_enabled() is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_client_init_failure_disables_tracing(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    from engine.config import get_settings
    get_settings.cache_clear()

    import langfuse

    def exploding(**kw):
        raise RuntimeError("bad credentials")

    monkeypatch.setattr(langfuse, "Langfuse", exploding)
    try:
        tracing.init_tracing()
        assert tracing.tracing_enabled() is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

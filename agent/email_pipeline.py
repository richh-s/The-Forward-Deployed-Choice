"""
Outreach email pipeline — routing, Langfuse tracing, result normalisation.

Composition + tone-gating (scoring, regeneration loop, roast test) now live in
agent.email_agent.compose_with_tone_gate. This module is the thin outer shell:
it calls that function, wraps results in the standard status dict that main.py
and run_synthetic_traces.py expect, and handles Langfuse tracing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.email_agent import (
    compose_with_tone_gate,
    linkedin_roast_test,
    COMPOSER_MODEL,
    JUDGE_MODEL,
    MAX_ATTEMPTS,
    SCORE_THRESHOLD,
    ESCALATION_THRESHOLD,
)

__all__ = [
    "compose_with_regeneration",
    "linkedin_roast_test",      # re-exported for callers that imported from here
    "COMPOSER_MODEL",
    "JUDGE_MODEL",
    "MAX_ATTEMPTS",
    "SCORE_THRESHOLD",
    "ESCALATION_THRESHOLD",
]


def _maybe_create_langfuse_trace(name: str, metadata: dict) -> Optional[str]:
    """Create a Langfuse trace if credentials are present; return its id."""
    try:
        from langfuse import Langfuse  # type: ignore

        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return None
        lf = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        )
        trace = lf.trace(name=name, metadata=metadata)
        lf.flush()
        return getattr(trace, "id", None)
    except Exception:
        return None


def compose_with_regeneration(
    hiring_signal_brief: dict,
    competitor_gap_brief: dict,
    bench_summary: dict,
    prior_thread: Optional[dict] = None,
    pricing_in_scope: bool = False,
) -> dict:
    """Compose an outreach email with full tone-preservation gating.

    Delegates composition + scoring + regeneration to compose_with_tone_gate in
    agent.email_agent, then wraps the result in the normalised status dict that
    main.py and run_synthetic_traces.py consume.

    Returns:
      {
        "status": "sent" | "escalated" | "roast_fail" | "error",
        "subject": str,
        "body": str,
        "attempts": int,
        "final_scores": dict,          # tone marker scores from last attempt
        "failed_markers": list[str],
        "roast_verdict": "NO" | "YES" | "SKIPPED",
        "langfuse_trace_id": str | None,
        "model_used": str,
        "judge_model_used": str,
        "draft": dict,                 # full composer JSON (for HubSpot logging etc.)
        "usage": dict,
        "reason": str,
        "deterministic_failures": list[str],
        "regeneration_count": int,
      }
    """
    is_re_engagement = prior_thread is not None

    langfuse_trace_id = _maybe_create_langfuse_trace(
        name="email-pipeline",
        metadata={
            "is_re_engagement": is_re_engagement,
            "pricing_in_scope": pricing_in_scope,
            "composer_model": COMPOSER_MODEL,
            "judge_model": JUDGE_MODEL,
        },
    )

    draft, usage, gate = compose_with_tone_gate(
        brief=hiring_signal_brief,
        competitor_brief=competitor_gap_brief,
        bench_summary=bench_summary,
        is_re_engagement=is_re_engagement,
        pricing_in_scope=pricing_in_scope,
    )

    status = gate.get("status", "error")
    marker_scores = gate.get("marker_scores") or {}
    failed_markers = gate.get("failed_markers") or []
    det_failures = gate.get("det_failures") or []
    attempts_made = gate.get("attempt", 1)

    return {
        "status": status,
        "subject": (draft or {}).get("subject", ""),
        "body": (draft or {}).get("body", ""),
        "attempts": attempts_made,
        "final_scores": marker_scores,
        "failed_markers": failed_markers,
        "roast_verdict": gate.get("roast_verdict", "SKIPPED"),
        "langfuse_trace_id": langfuse_trace_id,
        "model_used": COMPOSER_MODEL,
        "judge_model_used": JUDGE_MODEL,
        "draft": draft or {},
        "usage": usage,
        "reason": gate.get("reason", ""),
        "deterministic_failures": det_failures,
        "regeneration_count": max(0, attempts_made - 1),
    }

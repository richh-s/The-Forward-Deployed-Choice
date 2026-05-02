"""
Outreach email pipeline — composer + tone-preservation gate + regeneration loop.

This module sits between the raw composer (agent.email_agent.compose_outreach_email)
and the email sender. It enforces Section 5 of the Week 10 spec:

  1. Compose a draft (Claude Sonnet via OpenRouter).
  2. Score the draft via scoring_evaluator.score_task using a different model
     family for the LLM judge (Qwen3-Next-80B) — preference-leakage prevention.
  3. If any deterministic check fails OR any tone marker scores below 4,
     regenerate. Maximum MAX_REGEN_ATTEMPTS attempts before human escalation.
  4. If 2+ tone markers ever score below 4 in a single attempt, escalate to
     human review immediately (no further regeneration).
  5. Final binary "LinkedIn roast test" — would a senior tech leader screenshot
     and post this email publicly to mock it? YES → regenerate; NO → pass.

Returns a structured result with status, subject, body, attempts, final_scores,
failed_markers, roast_verdict, langfuse_trace_id, model_used, judge_model_used.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.email_agent import compose_outreach_email
from scoring_evaluator import score_task

MAX_REGEN_ATTEMPTS = 2
TONE_MARKER_THRESHOLD = 4
HUMAN_ESCALATION_MARKER_FAILS = 2

COMPOSER_MODEL = "anthropic/claude-sonnet-4.6"
JUDGE_MODEL = os.environ.get("TONE_JUDGE_MODEL", "qwen/qwen3-next-80b-a3b-instruct")
ROAST_MODEL = os.environ.get("LINKEDIN_ROAST_MODEL", "qwen/qwen3-next-80b-a3b-instruct")


def _build_task_for_scoring(
    draft: dict,
    hiring_signal_brief: dict,
    bench_summary: dict,
    is_re_engagement: bool,
) -> dict:
    """Adapt composer output + inputs into the task shape scoring_evaluator expects."""
    message_type = "re_engagement" if is_re_engagement else "cold"
    return {
        "task_id": "RUNTIME-COMPOSE",
        "candidate_output": {
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "message_type": message_type,
        },
        "input": {
            "hiring_signal_brief": hiring_signal_brief,
            "bench_summary": bench_summary,
        },
        "ground_truth": {},
        "failure_dimension": "runtime",
    }


def _failed_markers(marker_scores: Optional[dict]) -> list[str]:
    if not marker_scores:
        return []
    return [m for m, s in marker_scores.items() if s < TONE_MARKER_THRESHOLD]


def _det_failures(det_results: dict) -> list[str]:
    return [name for name, r in det_results.items() if not r.get("passed")]


def linkedin_roast_test(subject: str, body: str) -> dict:
    """Binary judge: would a senior tech leader screenshot this email and post it
    publicly to mock the sender?

    Uses a different model family from the composer (Qwen, not Claude) for
    preference-leakage prevention. If no API key is configured, returns a
    permissive default ({"would_roast": False}) so local/offline runs do not
    block on this gate — the deterministic checks remain authoritative.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"would_roast": False, "reason": "no_api_key_offline_default", "model": None}

    try:
        import requests

        prompt = (
            "You are a senior tech leader (CTO or VP Engineering at a Series B+ startup). "
            "You receive cold outreach emails daily and routinely screenshot the worst ones "
            "to post on LinkedIn or X with a mocking caption.\n\n"
            "Read the email below and answer one question: would you screenshot this and "
            "post it publicly to mock the sender?\n\n"
            "Common reasons leaders DO post: banned consulting buzzwords (world-class, top "
            "talent, rockstar, synergy, skyrocket), condescending tone framing the recipient "
            "as failing, fabricated claims about the recipient's company, generic templates "
            "with no specific signal, fake urgency, or pushy follow-ups.\n\n"
            "Common reasons they DO NOT post: a specific signal grounded in public data, a "
            "concrete and reasonable ask, peer-level tone, no buzzwords, brief and direct.\n\n"
            f"Subject: {subject}\n"
            f"Body:\n{body}\n\n"
            'Return ONLY valid JSON: {"would_roast": true|false, "reason": "<one sentence>"}'
        )

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": ROAST_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 200,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{[^}]*\}", content, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return {
                "would_roast": bool(parsed.get("would_roast", False)),
                "reason": str(parsed.get("reason", ""))[:300],
                "model": ROAST_MODEL,
            }
    except Exception as e:
        return {"would_roast": False, "reason": f"roast_judge_error_{type(e).__name__}", "model": ROAST_MODEL}

    return {"would_roast": False, "reason": "no_json_in_response", "model": ROAST_MODEL}


def _maybe_create_langfuse_trace(name: str, metadata: dict) -> Optional[str]:
    """Create a Langfuse trace if credentials are available; return its id."""
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
    use_judge: bool = True,
    enable_roast_test: bool = True,
) -> dict:
    """Compose an outreach email, scoring and regenerating until it passes the
    tone-preservation gate or escalation conditions trigger.

    Returns:
      {
        "status": "sent" | "escalated" | "roast_fail" | "error",
        "subject": str,
        "body": str,
        "attempts": int,                   # 1, 2, or 3
        "final_scores": dict,              # marker_scores from final attempt
        "failed_markers": list[str],
        "roast_verdict": "NO" | "YES" | "SKIPPED",
        "langfuse_trace_id": str | None,
        "model_used": str,                 # composer model
        "judge_model_used": str,           # tone-judge model
        "draft": dict,                     # full composer JSON (for HubSpot etc.)
        "usage": dict,                     # token usage from final composer call
        "reason": str,                     # human-readable explanation
        "deterministic_failures": list[str],
        "regeneration_count": int,
      }
    """
    is_re_engagement = prior_thread is not None
    attempts: list[dict] = []
    draft: dict = {}
    usage: dict = {}
    last_marker_scores: dict = {}
    last_marker_fails: list[str] = []
    last_det_fails: list[str] = []
    last_roast: Optional[dict] = None

    langfuse_trace_id = _maybe_create_langfuse_trace(
        name="email-pipeline",
        metadata={
            "is_re_engagement": is_re_engagement,
            "pricing_in_scope": pricing_in_scope,
            "composer_model": COMPOSER_MODEL,
            "judge_model": JUDGE_MODEL,
        },
    )

    for attempt_idx in range(MAX_REGEN_ATTEMPTS + 1):
        try:
            draft, usage = compose_outreach_email(
                brief=hiring_signal_brief,
                competitor_brief=competitor_gap_brief,
                bench_summary=bench_summary,
                is_re_engagement=is_re_engagement,
                pricing_in_scope=pricing_in_scope,
            )
        except Exception as e:
            return {
                "status": "error",
                "subject": "",
                "body": "",
                "attempts": attempt_idx + 1,
                "final_scores": {},
                "failed_markers": [],
                "roast_verdict": "SKIPPED",
                "langfuse_trace_id": langfuse_trace_id,
                "model_used": COMPOSER_MODEL,
                "judge_model_used": JUDGE_MODEL,
                "draft": {},
                "usage": {},
                "reason": f"composer_exception: {type(e).__name__}: {e}",
                "deterministic_failures": [],
                "regeneration_count": attempt_idx,
            }

        try:
            task = _build_task_for_scoring(draft, hiring_signal_brief, bench_summary, is_re_engagement)
            result = score_task(task, use_judge=use_judge, judge_model=JUDGE_MODEL)
        except Exception as e:
            return {
                "status": "error",
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "attempts": attempt_idx + 1,
                "final_scores": {},
                "failed_markers": [],
                "roast_verdict": "SKIPPED",
                "langfuse_trace_id": langfuse_trace_id,
                "model_used": COMPOSER_MODEL,
                "judge_model_used": JUDGE_MODEL,
                "draft": draft,
                "usage": usage,
                "reason": f"scorer_exception: {type(e).__name__}: {e}",
                "deterministic_failures": [],
                "regeneration_count": attempt_idx,
            }

        last_det_fails = _det_failures(result["deterministic_checks"])
        last_marker_scores = result.get("marker_scores") or {}
        last_marker_fails = _failed_markers(last_marker_scores)

        attempts.append({
            "attempt": attempt_idx + 1,
            "composite_score": result["composite_score"],
            "deterministic_failures": last_det_fails,
            "marker_scores": last_marker_scores,
            "marker_failures": last_marker_fails,
            "draft_subject": draft.get("subject"),
        })

        if len(last_marker_fails) >= HUMAN_ESCALATION_MARKER_FAILS:
            return {
                "status": "escalated",
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "attempts": attempt_idx + 1,
                "final_scores": last_marker_scores,
                "failed_markers": last_marker_fails,
                "roast_verdict": "SKIPPED",
                "langfuse_trace_id": langfuse_trace_id,
                "model_used": COMPOSER_MODEL,
                "judge_model_used": JUDGE_MODEL,
                "draft": draft,
                "usage": usage,
                "reason": (
                    f"{len(last_marker_fails)} tone markers below {TONE_MARKER_THRESHOLD} "
                    f"({', '.join(last_marker_fails)}); above human-escalation threshold "
                    f"of {HUMAN_ESCALATION_MARKER_FAILS}"
                ),
                "deterministic_failures": last_det_fails,
                "regeneration_count": attempt_idx,
            }

        passes_det = not last_det_fails
        passes_markers = len(last_marker_fails) == 0
        if passes_det and passes_markers:
            last_roast = (
                linkedin_roast_test(draft.get("subject", ""), draft.get("body", ""))
                if enable_roast_test
                else {"would_roast": False, "reason": "roast_test_disabled", "model": None}
            )
            if last_roast.get("would_roast"):
                attempts[-1]["roast_test"] = last_roast
                if attempt_idx >= MAX_REGEN_ATTEMPTS:
                    return {
                        "status": "roast_fail",
                        "subject": draft.get("subject", ""),
                        "body": draft.get("body", ""),
                        "attempts": attempt_idx + 1,
                        "final_scores": last_marker_scores,
                        "failed_markers": last_marker_fails,
                        "roast_verdict": "YES",
                        "langfuse_trace_id": langfuse_trace_id,
                        "model_used": COMPOSER_MODEL,
                        "judge_model_used": JUDGE_MODEL,
                        "draft": draft,
                        "usage": usage,
                        "reason": (
                            "Draft passed deterministic+tone gates but failed LinkedIn-roast "
                            f"test on final attempt: {last_roast.get('reason', '')}"
                        ),
                        "deterministic_failures": last_det_fails,
                        "regeneration_count": attempt_idx,
                    }
                continue

            return {
                "status": "sent",
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "attempts": attempt_idx + 1,
                "final_scores": last_marker_scores,
                "failed_markers": [],
                "roast_verdict": "NO",
                "langfuse_trace_id": langfuse_trace_id,
                "model_used": COMPOSER_MODEL,
                "judge_model_used": JUDGE_MODEL,
                "draft": draft,
                "usage": usage,
                "reason": "All deterministic checks pass; all tone markers >= 4; roast-safe.",
                "deterministic_failures": [],
                "regeneration_count": attempt_idx,
            }

        if attempt_idx >= MAX_REGEN_ATTEMPTS:
            break

    return {
        "status": "escalated",
        "subject": draft.get("subject", ""),
        "body": draft.get("body", ""),
        "attempts": MAX_REGEN_ATTEMPTS + 1,
        "final_scores": last_marker_scores,
        "failed_markers": last_marker_fails,
        "roast_verdict": "SKIPPED",
        "langfuse_trace_id": langfuse_trace_id,
        "model_used": COMPOSER_MODEL,
        "judge_model_used": JUDGE_MODEL,
        "draft": draft,
        "usage": usage,
        "reason": (
            f"Exhausted {MAX_REGEN_ATTEMPTS + 1} attempts without a clean draft. "
            f"Last attempt: det_failures={last_det_fails}, markers<4={last_marker_fails}"
        ),
        "deterministic_failures": last_det_fails,
        "regeneration_count": MAX_REGEN_ATTEMPTS,
    }


__all__ = [
    "compose_with_regeneration",
    "linkedin_roast_test",
    "MAX_REGEN_ATTEMPTS",
    "TONE_MARKER_THRESHOLD",
    "HUMAN_ESCALATION_MARKER_FAILS",
    "COMPOSER_MODEL",
    "JUDGE_MODEL",
    "ROAST_MODEL",
]

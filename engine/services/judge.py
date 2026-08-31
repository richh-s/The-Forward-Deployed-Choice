"""LLM judge quality gate.

Every draft is scored before it reaches the approval queue. The rubric mirrors
the dimensions from the Tenacious-Bench work (signal grounding, mode
compliance, tone, structure, hallucination risk); the composite score drives
auto-approval and low scores trigger one regeneration attempt.
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Workspace
from engine.services import llm

# NOTE: no `minimum`/`maximum` on the number properties. The structured-output
# API rejects those keywords outright ("For 'number' type, properties maximum,
# minimum are not supported"), which failed every judge call with a 400. The
# range is stated in each description so the model still targets it, and
# _clamp01() below enforces it on the way in — the schema was never what
# guaranteed the bound.
_SCORE = {
    "type": "number",
    "description": "Score from 0.0 (worst) to 1.0 (best).",
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "signal_grounding": _SCORE,
        "mode_compliance": _SCORE,
        "tone": _SCORE,
        "structure": _SCORE,
        "hallucination_free": _SCORE,
        "feedback": {
            "type": "string",
            "description": "One or two sentences: the biggest problem, or why it passes",
        },
    },
    "required": [
        "signal_grounding", "mode_compliance", "tone",
        "structure", "hallucination_free", "feedback",
    ],
    "additionalProperties": False,
}

# hallucination_free is weighted highest: an ungrounded claim is the failure
# mode this product exists to prevent.
WEIGHTS = {
    "signal_grounding": 0.25,
    "mode_compliance": 0.20,
    "tone": 0.15,
    "structure": 0.10,
    "hallucination_free": 0.30,
}

JUDGE_SYSTEM = """You are a strict quality judge for outbound sales emails.
You score drafts against the signal brief they were composed from.

Score each dimension from 0.0 to 1.0:
- signal_grounding: every claim in the email traces to a signal in the brief
- mode_compliance: assertion mode only with high-confidence signals; inquiry
  mode asks rather than asserts
- tone: professional, concise, not pushy, no marketing fluff
- structure: subject under 60 chars, body under ~120 words, clear single ask
- hallucination_free: 1.0 only if NOTHING in the email is invented — no made-up
  names, numbers, events, or capabilities. Any fabrication scores 0.0.

Be adversarial: assume the email is guilty until the brief proves it innocent."""


def _clamp01(x) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def composite_score(scores: dict) -> float:
    # Local models don't strictly honor the schema's min/max, so clamp.
    base = sum(_clamp01(scores.get(k, 0.0)) * w for k, w in WEIGHTS.items())
    # A fabrication is disqualifying regardless of how good the rest is:
    # cap the composite below both the regeneration and auto-approve bars.
    if _clamp01(scores.get("hallucination_free", 0.0)) < 0.5:
        return min(base, 0.4)
    return base


async def judge_draft(
    db: AsyncSession,
    workspace: Workspace,
    *,
    subject: str,
    body: str,
    mode: str,
    avg_confidence: float,
    signals: dict,
) -> tuple[float, str, float, dict]:
    """Score a draft. Returns (composite score 0..1, feedback, llm cost usd,
    per-dimension scores clamped to [0, 1])."""
    user_prompt = f"""Signal brief the email was composed from:
{json.dumps(signals, indent=2)}

Declared mode: {mode} (avg signal confidence {avg_confidence:.2f})

Email under review:
Subject: {subject}

{body}
"""
    result = await llm.complete(
        db,
        workspace.id,
        model=llm.model_for(workspace, "judge"),
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=4096,
        effort="low",
        json_schema=JUDGE_SCHEMA,
        role="judge",
        trace_metadata={"mode": mode, "avg_confidence": avg_confidence},
    )
    scores = result.json()
    dimensions = {k: _clamp01(scores.get(k, 0.0)) for k in WEIGHTS}
    return (
        composite_score(scores),
        scores.get("feedback", ""),
        result.cost_usd,
        dimensions,
    )

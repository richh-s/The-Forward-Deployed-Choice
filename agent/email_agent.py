from openai import OpenAI
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.load_seed import build_system_prompt_context, build_few_shot_block

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
)

_SEED_CONTEXT = None

def _get_seed_context() -> str:
    global _SEED_CONTEXT
    if _SEED_CONTEXT is None:
        _SEED_CONTEXT = build_system_prompt_context()
    return _SEED_CONTEXT

_FEW_SHOT_BLOCK = None

def _get_few_shot_block() -> str:
    global _FEW_SHOT_BLOCK
    if _FEW_SHOT_BLOCK is None:
        _FEW_SHOT_BLOCK = build_few_shot_block(n_transcripts=3)
    return _FEW_SHOT_BLOCK


SYSTEM_PROMPT_TEMPLATE = """\
You are an outreach agent for Tenacious Consulting and Outsourcing.
Tenacious provides managed talent outsourcing and project consulting to B2B tech companies.

{seed_context}

HONESTY CONSTRAINTS — hard rules, never violate:
1. Only assert claims directly supported by the hiring signal brief.
2. If signal confidence is "low" or "medium" AND open_roles < 5, use inquiry language not assertion language.
3. Never use the word "offshore" in first contact.
4. Never commit to engineering-team capacity not confirmed in the bench summary above.
5. Never pitch Segment 4 to a prospect with ai_maturity_score below 2.
6. Route to human for pricing beyond public bands.
7. If competitor gap confidence is "medium", say "peers like X" not "you are behind X".
8. Keep first email under 120 words in the body.
9. Do not use "bench" — say "engineering team" or "available capacity" instead.
10. Subject line must start with Request, Follow-up, Context, or Question. Under 60 characters. No emojis.

KILL-SWITCH RULE:
Compute avg_confidence across all 6 signals.
If avg_confidence < 0.70 → Inquiry Mode (ask, do not assert)
If avg_confidence >= 0.70 → Assertion Mode (state verified facts)

DISCOVERY TRANSCRIPT EXAMPLES (tone and structure reference):
{few_shot_block}
"""

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        seed_context=_get_seed_context(),
        few_shot_block=_get_few_shot_block(),
    )


def compute_avg_confidence(signals: dict) -> float:
    keys = [
        "signal_1_funding_event",
        "signal_2_job_post_velocity",
        "signal_3_layoff_event",
        "signal_4_leadership_change",
        "signal_5_ai_maturity",
        "signal_6_icp_segment",
    ]
    scores = [
        CONFIDENCE_MAP.get(str(signals[k].get("confidence", "low")).lower(), 0.4)
        for k in keys if k in signals
    ]
    return sum(scores) / len(scores) if scores else 0.0


def compose_outreach_email(
    brief: dict,
    competitor_brief: dict,
    bench_summary: dict
) -> dict:
    avg_conf = compute_avg_confidence(brief["signals"])
    mode = "ASSERTION" if avg_conf >= 0.70 else "INQUIRY"

    prompt = f"""
Compose a cold outreach email for this prospect.
Mode: {mode} (avg signal confidence: {avg_conf:.2f})

Hiring Signal Brief:
{json.dumps(brief, indent=2)}

Competitor Gap Brief:
{json.dumps(competitor_brief, indent=2)}

Available engineering team capacity:
{json.dumps(bench_summary, indent=2)}

Return valid JSON only — no markdown, no backticks:
{{
  "subject": "string (under 60 chars, starts with Request/Follow-up/Context/Question)",
  "body": "string (plain text, under 120 words)",
  "variant_tag": "signal_grounded" or "generic",
  "mode_used": "assertion" or "inquiry",
  "avg_confidence": float
}}
"""
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        max_tokens=700,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt}
        ]
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return json.loads(text), dict(response.usage)

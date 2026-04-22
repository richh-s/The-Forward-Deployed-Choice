from openai import OpenAI
import os
import json

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
)

SYSTEM_PROMPT = """You are an outreach agent for Tenacious Consulting and Outsourcing.
Tenacious provides managed talent outsourcing and project consulting to B2B tech companies.

HONESTY CONSTRAINTS — hard rules, never violate:
1. Only assert claims directly supported by the hiring_signal_brief
2. If signal confidence is "low" or "medium" AND open_roles < 5,
   use inquiry language not assertion language
3. Never use the word "offshore" in first contact
4. Never commit to bench capacity not in bench_summary
5. Never pitch Segment 4 to ai_maturity_score below 2
6. Route to human for pricing beyond public bands
7. If competitor gap confidence is "medium", say "peers like X" not "you are behind"
8. Keep first email under 150 words

KILL-SWITCH RULE:
Compute avg_confidence across all 6 signals.
If avg_confidence < 0.70 → Inquiry Mode (ask, do not assert)
If avg_confidence >= 0.70 → Assertion Mode (state verified facts)"""

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}


def compute_avg_confidence(signals: dict) -> float:
    keys = [
        "signal_1_funding_event",
        "signal_2_job_post_velocity",
        "signal_3_layoff_event",
        "signal_4_leadership_change",
        "signal_5_ai_maturity",
        "signal_6_icp_segment"
    ]
    scores = [
        CONFIDENCE_MAP.get(signals[k]["confidence"], 0.4)
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

Available Bench:
{json.dumps(bench_summary, indent=2)}

Return valid JSON only — no markdown, no backticks:
{{
  "subject": "string",
  "body": "string (HTML)",
  "variant_tag": "signal_grounded" or "generic",
  "mode_used": "assertion" or "inquiry",
  "avg_confidence": float
}}
"""
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return json.loads(text), dict(response.usage)

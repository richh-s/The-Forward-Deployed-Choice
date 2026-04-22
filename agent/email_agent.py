import anthropic
import os
import json

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
    response = client.messages.create(
        model="claude-sonnet-4-5-20251022",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return json.loads(response.content[0].text), response.usage

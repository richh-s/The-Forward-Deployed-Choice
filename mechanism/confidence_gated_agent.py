"""
Confidence-Gated Phrasing + ICP Abstention mechanism.
Controlled by ASSERTION_THRESHOLD, ABSTENTION_THRESHOLD, CONFLICT_ABSTENTION env vars.
Run:  python mechanism/confidence_gated_agent.py
"""
import anthropic
import json
import os

from langfuse import Langfuse

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
langfuse = Langfuse()

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}

# Ablation hyperparameters — override via env vars
ASSERTION_THRESHOLD = float(os.environ.get("ASSERTION_THRESHOLD", "0.70"))
ABSTENTION_THRESHOLD = float(os.environ.get("ABSTENTION_THRESHOLD", "0.50"))
CONFLICT_ABSTENTION = os.environ.get("CONFLICT_ABSTENTION", "True") == "True"

MODEL = "claude-sonnet-4-6"


def compute_signal_confidence(signals: dict) -> dict:
    signal_prefixes = [f"signal_{i}_" for i in range(1, 7)]
    signal_keys = [k for k in signals if any(k.startswith(p) for p in signal_prefixes)]
    scores = []
    for key in signal_keys:
        conf = signals[key].get("confidence", "low")
        scores.append(CONFIDENCE_MAP.get(conf, 0.4))
    avg = sum(scores) / len(scores) if scores else 0.0
    return {
        "avg_confidence": avg,
        "mode": "assertion" if avg >= ASSERTION_THRESHOLD else "inquiry",
        "signal_count": len(scores),
        "scores": scores
    }


def should_abstain(signals: dict, conf_result: dict) -> tuple[bool, str]:
    icp = signals.get("signal_6_icp_segment", {})

    if icp.get("segment_number", 0) == 0:
        return True, "unclassified_prospect"

    if CONFLICT_ABSTENTION and icp.get("conflict_flag", False):
        return True, "icp_conflict_detected"

    icp_confidence = CONFIDENCE_MAP.get(icp.get("confidence", "low"), 0.4)
    if icp_confidence < ABSTENTION_THRESHOLD:
        return True, f"icp_confidence_below_threshold_{ABSTENTION_THRESHOLD}"

    if conf_result["avg_confidence"] < ABSTENTION_THRESHOLD:
        return True, f"avg_signal_confidence_below_threshold_{ABSTENTION_THRESHOLD}"

    return False, ""


def compose_with_mechanism(brief: dict, competitor_brief: dict, bench: dict) -> dict:
    signals = brief["signals"]
    conf_result = compute_signal_confidence(signals)
    abstain, abstain_reason = should_abstain(signals, conf_result)
    icp = signals.get("signal_6_icp_segment", {})

    if abstain:
        system = """You are a Tenacious Consulting outreach agent.
Send a generic exploratory email. Do NOT make specific claims about the prospect's business.
Ask open questions. Do not pitch a specific service. Keep under 100 words."""
        prompt = f"""
Prospect company: {brief.get('company', 'Unknown')}
Reason for generic mode: {abstain_reason}
Return JSON only: {{"subject": "string", "body": "string",
"variant_tag": "generic", "mode_used": "abstention",
"abstain_reason": "{abstain_reason}"}}
"""
    else:
        system = f"""You are a Tenacious Consulting outreach agent.
Mode: {conf_result['mode'].upper()} (avg confidence: {conf_result['avg_confidence']:.2f})
ICP Segment: {icp.get('label', 'Unknown')}

HONESTY CONSTRAINTS:
- Assertion mode: state verified facts from brief only
- Inquiry mode: ask rather than assert for all medium/low confidence signals
- Never use "offshore" in first contact
- Never commit to bench capacity beyond bench_summary
- Never pitch Segment 4 to ai_maturity_score < 2
- If competitor gap confidence is medium/low: frame as observation, not fact
- Under 150 words"""
        prompt = f"""
Hiring Signal Brief: {json.dumps(brief, indent=2)}
Competitor Gap Brief: {json.dumps(competitor_brief, indent=2)}
Bench Summary: {json.dumps(bench, indent=2)}
Return JSON only: {{"subject": "string", "body": "string",
"variant_tag": "signal_grounded", "mode_used": "{conf_result['mode']}",
"avg_confidence": {conf_result['avg_confidence']:.3f}}}
"""

    trace = langfuse.trace(name="mechanism-compose", metadata={
        "company": brief.get("company"),
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "avg_confidence": conf_result["avg_confidence"],
        "assertion_threshold": ASSERTION_THRESHOLD,
        "abstention_threshold": ABSTENTION_THRESHOLD,
        "conflict_abstention": CONFLICT_ABSTENTION
    })

    response = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    cost_usd = (
        response.usage.input_tokens * 0.000003 +
        response.usage.output_tokens * 0.000015
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    result = json.loads(text)
    result["trace_id"] = trace.id
    result["cost_usd"] = cost_usd
    result["abstain"] = abstain
    result["abstain_reason"] = abstain_reason
    result["avg_confidence"] = conf_result["avg_confidence"]
    result["mode"] = conf_result["mode"] if not abstain else "abstention"
    return result


if __name__ == "__main__":
    # Demo run with NovaPay brief
    import sys
    sys.path.insert(0, ".")
    from enrichment.mock_brief import HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF, BENCH_SUMMARY

    print(f"ASSERTION_THRESHOLD={ASSERTION_THRESHOLD}")
    print(f"ABSTENTION_THRESHOLD={ABSTENTION_THRESHOLD}")
    print(f"CONFLICT_ABSTENTION={CONFLICT_ABSTENTION}\n")

    result = compose_with_mechanism(HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF, BENCH_SUMMARY)
    print(json.dumps(result, indent=2))

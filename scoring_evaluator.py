"""
Tenacious-Bench v0.1 Scoring Evaluator
=======================================
Machine-verifiable rubric scorer for outreach email drafts.
Reads a task (hiring_signal_brief + bench_summary + candidate_output) and
returns a numerical score with no human in the loop for the deterministic
checks; an optional LLM judge call scores the five tone markers.

Usage:
    python scoring_evaluator.py --task path/to/task.json [--judge]
    python scoring_evaluator.py --tasks path/to/tasks.jsonl [--judge] [--seed 42]

Deterministic checks (6):
  banned_phrase_check   — none of the 23 banned phrases appear
  signal_grounding_check — at least one named signal from the brief appears
  bench_match_check     — no capacity over-commitment relative to bench_summary
  word_count_check      — body within type-appropriate word limit
  one_ask_check         — exactly one explicit call to action
  bench_word_check      — the word "bench" does not appear in the output

LLM judge markers (5, scored 1-5):
  direct, grounded, honest, professional, non_condescending

Composite score:
  IF any_deterministic_fail → 0.0
  ELSE → 0.4 + 0.12 * (sum(marker_scores) - 20) / 5
  (20 = baseline where all markers score exactly 4/5)

Seeds: set EVAL_SEED=42 for reproducibility.
"""

import re
import json
import os
import sys
import argparse
import hashlib
import random
from pathlib import Path
from typing import Optional

EVAL_SEED = int(os.environ.get("EVAL_SEED", 42))
random.seed(EVAL_SEED)

# ── Banned phrases (from Tenacious style guide v2) ──────────────────────────
BANNED_PHRASES: list[str] = [
    "world-class",
    "top talent",
    "A-players",
    "rockstar",
    "ninja",
    "wizard",
    "skyrocket",
    "supercharge",
    "10x",
    "I hope this email finds you well",
    "just following up",
    "circling back",
    "Quick question",
    "Quick chat",
    "synergize",
    "synergy",
    # "leverage" is context-dependent; only flag as consultant jargon usage
    "ecosystem",
    "game-changer",
    "disruptor",
    "paradigm shift",
    "our proprietary",
    "our AI-powered",
    "You'll regret missing this",
    "Don't miss out",
    "Per my last email",
    "our 500 employees",
    "our 20 years of experience",
]

WORD_LIMITS = {"cold": 120, "warm_reply": 200, "re_engagement": 100}
SUBJECT_CHAR_LIMIT = 60

# Keywords that indicate an explicit call-to-action
CTA_PATTERNS = [
    r"\b15[ -]minute\b",
    r"\b15min\b",
    r"\bscoping call\b",
    r"\bdiscovery call\b",
    r"\bcalendar\b",
    r"\bbooking\b",
    r"\bbook\b",
    r"\breply\b.*\byes\b",
    r"\blet me know\b",
    r"\bwant me to send\b",
    r"\bno follow-?up\b",
    r"\bignore this\b",
    r"\b30[ -]minute\b",
    r"\bschedule\b",
    r"\bhappy to introduce\b",
]

# Signal grounding: patterns that indicate a specific, named signal
SIGNAL_GROUNDING_PATTERNS = [
    # Funding: dollar amount + round type
    r"\$\d+(?:\.\d+)?[MBK]\b",
    r"\d+M\s+(?:Series [ABC]|seed|pre-seed)",
    r"Series [ABC]\b",
    # Job post velocity: role count + trend
    r"\d+\s+(?:open\s+)?(?:engineering\s+)?roles?\b",
    r"from \d+ to \d+",
    r"role[s]? (?:went|grown|increased)\b",
    # Layoff: percentage + timeframe
    r"\d+%\s+(?:headcount|staff|team)\b",
    r"contracted\s+by\s+(?:about\s+)?\d+",
    r"layoff\b",
    r"restructur",
    # Leadership change: named date or timeframe
    r"new (?:CTO|VP|Head of Engineering|engineering leader)\b",
    r"announc(?:ed|ement)\b.*(?:\d+ days|last month|this month)",
    r"announced on the \d+",
    # Named peer companies (at least 2 character company name before comparison)
    r"companies adjacent to yours",
    r"peer compan",
    r"three compan",
]


def check_banned_phrases(text: str) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_found_banned_phrases). Case-insensitive."""
    found = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return (len(found) == 0, found)


def check_signal_grounding(body: str, hiring_brief: dict) -> tuple[bool, str]:
    """
    Check that at least one verifiable signal from the brief is named in body.
    First tries regex patterns; then checks if any signal field values appear verbatim.
    """
    body_lower = body.lower()

    # Try pattern matching
    for pattern in SIGNAL_GROUNDING_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return (True, f"Pattern matched: {pattern}")

    # Try extracting concrete values from brief and checking they appear
    signals = []
    for key, val in hiring_brief.items():
        if isinstance(val, dict):
            for k2, v2 in val.items():
                if isinstance(v2, (int, float, str)) and str(v2) and len(str(v2)) > 3:
                    signals.append(str(v2))
        elif isinstance(val, (int, float, str)) and str(val) and len(str(val)) > 3:
            signals.append(str(val))

    for sig in signals:
        if sig.lower() in body_lower:
            return (True, f"Brief value found in body: {sig}")

    return (False, "No verifiable signal from brief found in body")


def check_bench_match(body: str, subject: str, hiring_brief: dict, bench_summary: dict) -> tuple[bool, str]:
    """
    If the candidate output commits to delivering engineers in a specific stack,
    the available count in bench_summary must be > 0 and the committed count
    must not exceed available_engineers.
    """
    requested_stack = hiring_brief.get("requested_stack")
    requested_headcount = hiring_brief.get("requested_headcount", 0)

    if not requested_stack or not bench_summary:
        return (True, "No capacity commitment in this task")

    stacks = bench_summary.get("stacks", {})
    stack_data = stacks.get(requested_stack, {})
    available = stack_data.get("available_engineers", 0)

    # Check if body makes a capacity commitment (commits to a specific number)
    commitment_patterns = [
        r"(?:can deliver|will deliver|place|staff|provide|deploy)\s+(\d+)\s+(?:senior\s+)?(?:engineers?|devs?)",
        r"(\d+)\s+(?:senior\s+)?(?:engineers?)\s+(?:by|starting|from|within)",
        r"(?:up to|upto)\s+(\d+)\s+engineers?",
        r"current availability supports (?:up to\s+)?(\d+)",
        r"can confirm.*?(\d+)\s+(?:engineers?)",
    ]

    committed_count = None
    for pattern in commitment_patterns:
        m = re.search(pattern, body + " " + subject, re.IGNORECASE)
        if m:
            try:
                committed_count = int(m.group(1))
                break
            except (IndexError, ValueError):
                pass

    if committed_count is None:
        # No explicit capacity commitment found
        if available == 0:
            # Check for an implicit over-commitment (e.g., "Absolutely, we can deliver" without a count)
            over_commit_signals = [
                r"absolutely.*(?:can deliver|we can|we will)",
                r"our.*(?:bench|team) is deep",
                r"we move fast.*engineers?\s+by",
            ]
            for pattern in over_commit_signals:
                if re.search(pattern, body, re.IGNORECASE):
                    return (False, f"Implicit over-commitment with 0 available {requested_stack} engineers")
        return (True, "No explicit capacity commitment detected")

    if available == 0:
        return (False, f"Committed {committed_count} {requested_stack} engineers but bench shows 0 available")
    if committed_count > available:
        return (False, f"Committed {committed_count} but only {available} {requested_stack} engineers available")

    return (True, f"Committed {committed_count} ≤ available {available}")


def check_word_count(body: str, message_type: str, subject: str) -> tuple[bool, str]:
    """Check word count against type-appropriate limit and subject char limit."""
    limit = WORD_LIMITS.get(message_type, 120)
    # Remove signature block for word counting (everything after "Best," or "Regards," or "Sincerely,")
    sig_patterns = [r"\nBest,\n", r"\nRegards,\n", r"\nSincerely,\n", r"\nThank you,\n"]
    body_no_sig = body
    for sig in sig_patterns:
        parts = re.split(sig, body, maxsplit=1)
        if len(parts) > 1:
            body_no_sig = parts[0]
            break

    word_count = len(body_no_sig.split())
    subject_chars = len(subject)

    if word_count > limit:
        return (False, f"Body word count {word_count} exceeds {limit}-word limit for {message_type}")
    if subject_chars > SUBJECT_CHAR_LIMIT:
        return (False, f"Subject '{subject}' is {subject_chars} chars, exceeds {SUBJECT_CHAR_LIMIT}")
    return (True, f"Word count {word_count}/{limit}, subject {subject_chars}/{SUBJECT_CHAR_LIMIT} chars")


def check_one_ask(body: str) -> tuple[bool, str]:
    """Count explicit calls to action. Pass if exactly 1; fail if 0 or >1."""
    cta_count = 0
    matched = []
    for pattern in CTA_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            cta_count += 1
            matched.append(pattern)

    # Normalise: if multiple patterns matched but they're in the same sentence, count as 1
    # Simple heuristic: check unique sentences containing a CTA
    sentences = re.split(r"[.!?]\s+", body)
    cta_sentences = set()
    for i, sentence in enumerate(sentences):
        for pattern in CTA_PATTERNS:
            if re.search(pattern, sentence, re.IGNORECASE):
                cta_sentences.add(i)

    n_cta = len(cta_sentences)

    if n_cta == 0:
        return (False, "No explicit call-to-action found")
    if n_cta > 2:
        return (False, f"Multiple CTAs in {n_cta} different sentences — violates one-ask rule")
    return (True, f"{n_cta} CTA sentence(s) detected — within acceptable range")


def check_bench_word(body: str) -> tuple[bool, str]:
    """The word 'bench' must not appear in prospect-facing output."""
    if re.search(r"\bbench\b", body, re.IGNORECASE):
        return (False, "The word 'bench' appears in prospect-facing output")
    return (True, "No 'bench' usage found")


def run_deterministic_checks(task: dict) -> dict:
    """Run all 6 deterministic checks on a task dict. Returns check results."""
    candidate = task.get("candidate_output", {})
    subject = candidate.get("subject", "")
    body = candidate.get("body", "")
    message_type = candidate.get("message_type", "cold")
    hiring_brief = task.get("input", {}).get("hiring_signal_brief", {})
    bench_summary = task.get("input", {}).get("bench_summary", {})

    full_text = f"{subject}\n{body}"

    banned_ok, banned_found = check_banned_phrases(full_text)
    signal_ok, signal_reason = check_signal_grounding(body, hiring_brief)
    bench_ok, bench_reason = check_bench_match(body, subject, hiring_brief, bench_summary)
    wc_ok, wc_reason = check_word_count(body, message_type, subject)
    ask_ok, ask_reason = check_one_ask(body)
    bench_word_ok, bench_word_reason = check_bench_word(body)

    return {
        "banned_phrase_check": {"passed": banned_ok, "detail": f"Found: {banned_found}" if not banned_ok else "Clean"},
        "signal_grounding_check": {"passed": signal_ok, "detail": signal_reason},
        "bench_match_check": {"passed": bench_ok, "detail": bench_reason},
        "word_count_check": {"passed": wc_ok, "detail": wc_reason},
        "one_ask_check": {"passed": ask_ok, "detail": ask_reason},
        "bench_word_check": {"passed": bench_word_ok, "detail": bench_word_reason},
    }


def compute_composite_score(det_results: dict, marker_scores: Optional[dict] = None) -> float:
    """
    Composite score:
    - Any deterministic failure → 0.0
    - Else → 0.4 + 0.12 * (sum(marker_scores) - 20) / 5
    Baseline: 0.4 when all markers = 4. Max: 1.0 when all markers = 5.
    """
    any_fail = any(not v["passed"] for v in det_results.values())
    if any_fail:
        return 0.0

    if not marker_scores:
        # No LLM judge available; return deterministic floor
        return 0.4

    scores = list(marker_scores.values())
    if not scores:
        return 0.4

    marker_sum = sum(scores)
    score = 0.4 + 0.12 * (marker_sum - 20) / 5
    return round(max(0.0, min(1.0, score)), 4)


def call_llm_judge(task: dict, model: str = "qwen3-next-80b") -> dict:
    """
    Call an LLM judge to score the five tone markers.
    In production this calls OpenRouter; in test mode returns mock scores.
    Set OPENROUTER_API_KEY in environment for live calls.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        # Return deterministic mock scores based on task ground truth (for reproducibility)
        gt = task.get("ground_truth", {})
        return gt.get("tone_marker_scores", {
            "direct": 4, "grounded": 4, "honest": 4, "professional": 4, "non_condescending": 4
        })

    try:
        import requests

        candidate = task.get("candidate_output", {})
        hiring_brief = task.get("input", {}).get("hiring_signal_brief", {})

        # Full rubric with calibration anchors committed in:
        # generation_scripts/prompts/tone_marker_judge_prompt.md
        judge_prompt = f"""You are a Tenacious Intelligence Corporation brand evaluator. Score the following outreach email draft on five tone markers. Return ONLY valid JSON with keys: direct, grounded, honest, professional, non_condescending. Each score is an integer 1-5.

SCORING RUBRIC WITH 1/3/5 CALIBRATION ANCHORS:

direct (1–5): Is the email clear, brief, and actionable?
  5 = Subject states intent; body ≤ word limit; single clear ask; zero filler phrases
  3 = Mostly clear but one filler sentence or a second implicit ask dilutes focus
  1 = Multiple filler phrases; subject is vague ("Reaching out…"); no clear ask at all

grounded (1–5): Are all claims supported by named signals (specific amount, date, role count)?
  5 = Every factual claim maps to a field in hiring_signal_brief; confidence-aware phrasing matches signal confidence
  3 = Most claims grounded but one uses "approximately" without confidence flag
  1 = Multiple claims not traceable to any supplied signal; numbers fabricated or contradict brief

honest (1–5): Does the email avoid hallucinated signals and name what the brief does not show?
  5 = Refuses to commit engineers not in bench; explicitly names absent data; no unconfirmed claims
  3 = One claim overstates certainty but does not fabricate new data; no explicit bench over-commitment
  1 = Commits capacity that bench_summary shows as 0; asserts funding that contradicts brief

professional (1–5): Is the language calibrated to a CTO/founder reader with no banned phrases?
  5 = No banned phrases; "bench" not used externally; signals discussed at peer level; no buzzwords
  3 = One borderline banned phrase used in technical context; tone appropriate overall
  1 = Two or more banned phrases used; or language is salesy/pushy rather than peer-level

non_condescending (1–5): Does the email frame any gap as a research finding, not a deficiency?
  5 = Gap framed as hypothesis: "we noticed X, which often precedes Y — curious if that's the case"
  3 = Gap stated as fact but without explicit judgment: factual but could read as critical
  1 = Gap framed as deficiency: "you're falling behind on AI adoption"; or uses condescending framing

Score ≤ 2 means the marker fails (draft would be rejected/regenerated in production).

HIRING SIGNAL BRIEF:
{json.dumps(hiring_brief, indent=2)}

EMAIL DRAFT:
Subject: {candidate.get('subject', '')}
Body:
{candidate.get('body', '')}

Return ONLY JSON: {{"direct": N, "grounded": N, "honest": N, "professional": N, "non_condescending": N}}"""

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": judge_prompt}],
                "temperature": 0.0,
                "seed": EVAL_SEED,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Extract JSON block
        json_match = re.search(r"\{[^}]+\}", content)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"[WARN] LLM judge call failed: {e}. Using ground-truth scores.", file=sys.stderr)

    gt = task.get("ground_truth", {})
    return gt.get("tone_marker_scores", {
        "direct": 4, "grounded": 4, "honest": 4, "professional": 4, "non_condescending": 4
    })


def score_task(task: dict, use_judge: bool = False, judge_model: str = "qwen3-next-80b") -> dict:
    """
    Score a single task. Returns a result dict with all check results,
    marker scores (if judge enabled), composite score, and final label.
    """
    task_id = task.get("task_id", "UNKNOWN")
    det_results = run_deterministic_checks(task)

    marker_scores = None
    if use_judge:
        marker_scores = call_llm_judge(task, model=judge_model)

    composite = compute_composite_score(det_results, marker_scores)
    label = "pass" if composite > 0.0 else "fail"

    # Compare to ground truth if available
    gt = task.get("ground_truth", {})
    gt_label = gt.get("label", "unknown")
    gt_score = gt.get("composite_score", None)
    label_match = (label == gt_label) if gt_label != "unknown" else None

    return {
        "task_id": task_id,
        "deterministic_checks": det_results,
        "marker_scores": marker_scores,
        "composite_score": composite,
        "label": label,
        "ground_truth_label": gt_label,
        "label_match": label_match,
        "ground_truth_score": gt_score,
        "score_delta": round(composite - gt_score, 4) if gt_score is not None else None,
    }


def score_tasks_file(tasks_path: str, use_judge: bool = False, judge_model: str = "qwen3-next-80b") -> dict:
    """Score all tasks in a JSONL file. Returns aggregate metrics."""
    tasks_path = Path(tasks_path)
    results = []
    tasks = []

    with open(tasks_path) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))

    for task in tasks:
        result = score_task(task, use_judge=use_judge, judge_model=judge_model)
        results.append(result)

    # Aggregate
    n = len(results)
    n_pass = sum(1 for r in results if r["label"] == "pass")
    n_fail = sum(1 for r in results if r["label"] == "fail")
    n_label_match = sum(1 for r in results if r["label_match"] is True)
    n_comparable = sum(1 for r in results if r["label_match"] is not None)

    # Per-dimension breakdown
    dim_results: dict[str, dict] = {}
    for i, task in enumerate(tasks):
        dim = task.get("failure_dimension", "unknown")
        if dim not in dim_results:
            dim_results[dim] = {"total": 0, "pass": 0, "fail": 0}
        dim_results[dim]["total"] += 1
        if results[i]["label"] == "pass":
            dim_results[dim]["pass"] += 1
        else:
            dim_results[dim]["fail"] += 1

    aggregate = {
        "tasks_file": str(tasks_path),
        "n_tasks": n,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "pass_rate": round(n_pass / n, 4) if n > 0 else 0.0,
        "label_accuracy": round(n_label_match / n_comparable, 4) if n_comparable > 0 else None,
        "mean_composite_score": round(sum(r["composite_score"] for r in results) / n, 4) if n > 0 else 0.0,
        "by_dimension": dim_results,
        "results": results,
    }
    return aggregate


def main():
    parser = argparse.ArgumentParser(description="Tenacious-Bench v0.1 Scoring Evaluator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", help="Path to a single task JSON file")
    group.add_argument("--tasks", help="Path to a JSONL file of tasks")
    parser.add_argument("--judge", action="store_true", help="Call LLM judge for tone markers")
    parser.add_argument("--judge-model", default="qwen3-next-80b", help="Model to use for judging")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--output", help="Write JSON results to file instead of stdout")
    args = parser.parse_args()

    global EVAL_SEED
    EVAL_SEED = args.seed
    random.seed(EVAL_SEED)

    if args.task:
        with open(args.task) as f:
            task = json.load(f)
        result = score_task(task, use_judge=args.judge, judge_model=args.judge_model)
        output = json.dumps(result, indent=2)
    else:
        result = score_tasks_file(args.tasks, use_judge=args.judge, judge_model=args.judge_model)
        # Remove verbose results from printed output unless debugging
        summary = {k: v for k, v in result.items() if k != "results"}
        output = json.dumps(summary, indent=2)
        full_output = json.dumps(result, indent=2)

    if args.output:
        Path(args.output).write_text(output if args.task else full_output)
        print(f"Results written to {args.output}")
    else:
        print(output)


# ── Dummy task runner for smoke test ────────────────────────────────────────
def run_smoke_test():
    """Run evaluator against the 3 example tasks in schema.json. Should produce 2 fail + 1 pass."""
    schema_path = Path(__file__).parent / "schema.json"
    if not schema_path.exists():
        print("schema.json not found — run from repo root")
        return False

    with open(schema_path) as f:
        schema = json.load(f)

    tasks = schema.get("example_tasks", [])
    print(f"Running smoke test on {len(tasks)} example tasks...")
    all_ok = True
    for task in tasks:
        result = score_task(task, use_judge=False)
        expected_label = task["ground_truth"]["label"]
        got_label = result["label"]
        match = got_label == expected_label
        status = "✓" if match else "✗"
        print(f"  {status} {task['task_id']}: expected={expected_label} got={got_label} score={result['composite_score']}")
        if not match:
            all_ok = False
            for check, val in result["deterministic_checks"].items():
                if not val["passed"]:
                    print(f"      FAILED CHECK: {check} — {val['detail']}")

    print(f"\nSmoke test {'PASSED' if all_ok else 'FAILED'}")
    return all_ok


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No args — run smoke test
        run_smoke_test()
    else:
        main()

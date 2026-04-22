"""
Run three ablation conditions against 20 held-out test cases.
Writes ablation_results.json and held_out_traces.jsonl.

Usage:
  python mechanism/run_ablations.py [--n-tasks 20] [--configs baseline,mechanism_v1,mechanism_v2_strict]
"""
import argparse
import json
import os
import time
import statistics
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, ".")

from mechanism.ablations import ABLATION_CONFIGS
from mechanism.statistical_test import test_delta

# 20 held-out test cases that probe the confidence-gating logic
HELD_OUT_TASKS = [
    # Task 1–5: Happy path (should always pass)
    {"task_id": "HO-001", "scenario": "happy_path", "brief": {
        "company": "StreamlineAI", "contact": {"name": "Dana Wu", "title": "VP Engineering", "email": "dana@streamline.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 18000000, "round": "Series B", "days_ago": 30},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 18, "delta_60d": 12},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 2},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-002", "scenario": "happy_path", "brief": {
        "company": "FinFlow Corp", "contact": {"name": "Marcus Reid", "title": "CTO", "email": "mreid@finflow.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 32000000, "round": "Series C", "days_ago": 55},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 22, "delta_60d": 15},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 3},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 4, "label": "AI Capability", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Task 3–7: Low confidence signals (mechanism should switch to inquiry)
    {"task_id": "HO-003", "scenario": "low_confidence", "brief": {
        "company": "VagueTech", "contact": {"name": "Sam Lee", "title": "Head of Engineering", "email": "sam@vaguetech.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "low", "amount_usd": 5000000, "round": "Seed", "days_ago": 120},
            "signal_2_job_post_velocity": {"confidence": "low", "engineering_roles": 2, "delta_60d": 1},
            "signal_3_layoff_event": {"confidence": "low", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "low", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "low", "score": 1},
            "signal_6_icp_segment": {"confidence": "low", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-004", "scenario": "low_confidence", "brief": {
        "company": "NebulaSoft", "contact": {"name": "Priya Nair", "title": "CTO", "email": "pnair@nebula.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "low", "amount_usd": None, "round": None, "days_ago": None},
            "signal_2_job_post_velocity": {"confidence": "low", "engineering_roles": 3, "delta_60d": 2},
            "signal_3_layoff_event": {"confidence": "low", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "low", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "low", "score": 0},
            "signal_6_icp_segment": {"confidence": "low", "segment_number": 0, "label": "Unclassified", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Task 5–9: Conflict flags (mechanism_v1 should abstain)
    {"task_id": "HO-005", "scenario": "conflict_flag", "brief": {
        "company": "ConflictedCo", "contact": {"name": "Jordan Blake", "title": "VP Eng", "email": "jblake@conflicted.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 12000000, "round": "Series A", "days_ago": 45},
            "signal_2_job_post_velocity": {"confidence": "medium", "engineering_roles": 8, "delta_60d": 5},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": True, "pct_workforce": 15},
            "signal_4_leadership_change": {"confidence": "medium", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "medium", "score": 2},
            "signal_6_icp_segment": {"confidence": "medium", "segment_number": 1, "label": "Recently Funded", "conflict_flag": True}
        }
    }, "expected_pass": True},
    # Tasks 6–10: Bench capacity edge cases
    {"task_id": "HO-006", "scenario": "bench_edge", "brief": {
        "company": "MLHeavy Inc", "contact": {"name": "Alex Torres", "title": "Head of ML", "email": "atorres@mlheavy.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 25000000, "round": "Series B", "days_ago": 60},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 12, "delta_60d": 8},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 3},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 4, "label": "AI Capability", "conflict_flag": False}
        }
    }, "expected_pass": True, "probe": "bench_ml_zero"},
    # Tasks 7–12: Leadership change scenarios
    {"task_id": "HO-007", "scenario": "leadership_change", "brief": {
        "company": "TurnaRound Tech", "contact": {"name": "Casey Morgan", "title": "New CTO", "email": "cmorgan@turnaround.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "medium", "amount_usd": 8000000, "round": "Series A", "days_ago": 200},
            "signal_2_job_post_velocity": {"confidence": "medium", "engineering_roles": 6, "delta_60d": 4},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": True, "role": "CTO", "days_ago": 18},
            "signal_5_ai_maturity": {"confidence": "medium", "score": 1},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 3, "label": "Leadership Change", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-008", "scenario": "leadership_change", "brief": {
        "company": "Pivotware", "contact": {"name": "Sam Nakamura", "title": "Incoming VP Eng", "email": "snaka@pivotware.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 15000000, "round": "Series A", "days_ago": 90},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 10, "delta_60d": 6},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": True, "role": "VP Engineering", "days_ago": 25},
            "signal_5_ai_maturity": {"confidence": "high", "score": 2},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 3, "label": "Leadership Change", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Tasks 9–13: Cost pathology probes
    {"task_id": "HO-009", "scenario": "cost_probe", "brief": {
        "company": "DataMega Corp", "contact": {"name": "Taylor Kim", "title": "CTO", "email": "tkim@datamega.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 50000000, "round": "Series D", "days_ago": 20},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 30, "delta_60d": 18},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 3},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 4, "label": "AI Capability", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-010", "scenario": "cost_probe", "brief": {
        "company": "SmallSeed Labs", "contact": {"name": "Riley Park", "title": "Co-founder", "email": "rpark@smallseed.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "low", "amount_usd": 500000, "round": "Pre-seed", "days_ago": 180},
            "signal_2_job_post_velocity": {"confidence": "low", "engineering_roles": 1, "delta_60d": 0},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "low", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "low", "score": 0},
            "signal_6_icp_segment": {"confidence": "low", "segment_number": 0, "label": "Unclassified", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Tasks 11–15: Signal reliability
    {"task_id": "HO-011", "scenario": "stale_signal", "brief": {
        "company": "OldData Systems", "contact": {"name": "Quinn Lee", "title": "CTO", "email": "qlee@olddata.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "low", "amount_usd": 8000000, "round": "Series A", "days_ago": 95, "stale": True},
            "signal_2_job_post_velocity": {"confidence": "medium", "engineering_roles": 5, "delta_60d": 3},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "medium", "score": 1},
            "signal_6_icp_segment": {"confidence": "medium", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-012", "scenario": "stale_signal", "brief": {
        "company": "FreshData Inc", "contact": {"name": "Morgan Chen", "title": "VP Eng", "email": "mchen@freshdata.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 20000000, "round": "Series B", "days_ago": 10},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 15, "delta_60d": 10},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 2},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Tasks 13–17: Mixed confidence
    {"task_id": "HO-013", "scenario": "mixed_confidence", "brief": {
        "company": "MixedSignals AI", "contact": {"name": "Drew Adams", "title": "CTO", "email": "dadams@mixedsig.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 14000000, "round": "Series A", "days_ago": 50},
            "signal_2_job_post_velocity": {"confidence": "low", "engineering_roles": 2, "delta_60d": 1},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "low", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "low", "score": 1},
            "signal_6_icp_segment": {"confidence": "medium", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-014", "scenario": "mixed_confidence", "brief": {
        "company": "HighConfidence Ltd", "contact": {"name": "Sam Quinn", "title": "Eng Director", "email": "squinn@highconf.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 40000000, "round": "Series C", "days_ago": 25},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 25, "delta_60d": 16},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 2},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-015", "scenario": "mixed_confidence", "brief": {
        "company": "LowLow Tech", "contact": {"name": "Leslie Jones", "title": "CTO", "email": "ljones@lowlow.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "low", "amount_usd": 2000000, "round": "Seed", "days_ago": 200},
            "signal_2_job_post_velocity": {"confidence": "low", "engineering_roles": 1, "delta_60d": 0},
            "signal_3_layoff_event": {"confidence": "medium", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "low", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "low", "score": 0},
            "signal_6_icp_segment": {"confidence": "low", "segment_number": 0, "label": "Unclassified", "conflict_flag": False}
        }
    }, "expected_pass": True},
    # Tasks 16–20: AI maturity edge cases
    {"task_id": "HO-016", "scenario": "ai_maturity_edge", "brief": {
        "company": "AI-Light Fintech", "contact": {"name": "Pat Williams", "title": "CTO", "email": "pwilliams@ailight.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 22000000, "round": "Series B", "days_ago": 45},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 20, "delta_60d": 12},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 0, "strategic_choice": True},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-017", "scenario": "ai_maturity_edge", "brief": {
        "company": "DeepML Ventures", "contact": {"name": "Chris Park", "title": "Head of AI", "email": "cpark@deepml.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 60000000, "round": "Series D", "days_ago": 15},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 35, "delta_60d": 20},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 3},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 4, "label": "AI Capability", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-018", "scenario": "ai_maturity_edge", "brief": {
        "company": "Borderline AI Co", "contact": {"name": "Jordan Smith", "title": "ML Lead", "email": "jsmith@borderline.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "medium", "amount_usd": 10000000, "round": "Series A", "days_ago": 80},
            "signal_2_job_post_velocity": {"confidence": "medium", "engineering_roles": 7, "delta_60d": 4},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "medium", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "medium", "score": 1},
            "signal_6_icp_segment": {"confidence": "medium", "segment_number": 1, "label": "Recently Funded", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-019", "scenario": "ai_maturity_edge", "brief": {
        "company": "TrueAI Corp", "contact": {"name": "Avery Wong", "title": "CTO", "email": "awong@trueai.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 45000000, "round": "Series C", "days_ago": 30},
            "signal_2_job_post_velocity": {"confidence": "high", "engineering_roles": 28, "delta_60d": 18},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": False},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "high", "score": 2},
            "signal_6_icp_segment": {"confidence": "high", "segment_number": 4, "label": "AI Capability", "conflict_flag": False}
        }
    }, "expected_pass": True},
    {"task_id": "HO-020", "scenario": "conflict_flag", "brief": {
        "company": "Layoff-Funded Inc", "contact": {"name": "Robin Clarke", "title": "VP Eng", "email": "rclarke@lfunded.example"},
        "signals": {
            "signal_1_funding_event": {"confidence": "high", "amount_usd": 16000000, "round": "Series B", "days_ago": 35},
            "signal_2_job_post_velocity": {"confidence": "medium", "engineering_roles": 6, "delta_60d": 3},
            "signal_3_layoff_event": {"confidence": "high", "layoff_detected": True, "pct_workforce": 18},
            "signal_4_leadership_change": {"confidence": "high", "change_detected": False},
            "signal_5_ai_maturity": {"confidence": "medium", "score": 2},
            "signal_6_icp_segment": {"confidence": "medium", "segment_number": 1, "label": "Recently Funded", "conflict_flag": True}
        }
    }, "expected_pass": True},
]

BASE_BENCH = {
    "python_engineers": 4, "go_engineers": 2, "data_engineers": 3,
    "ml_engineers": 2, "infra_engineers": 1, "total_available": 12
}
BASE_COMPETITOR = {
    "sector": "fintech",
    "gaps": [
        {"competitor": "Stripe", "gap": "ML infrastructure", "confidence": "medium"},
        {"competitor": "Plaid", "gap": "AI ops tooling", "confidence": "low"}
    ]
}

PASS_CRITERIA = {
    "no_offshore": lambda out: "offshore" not in out.lower(),
    "no_hallucinated_amount": lambda out, brief: _check_no_hallucinated_amount(out, brief),
    "no_segment4_low_ai": lambda out, brief: _check_no_seg4_low_ai(out, brief),
}


def _check_no_hallucinated_amount(out: str, brief: dict) -> bool:
    sig1 = brief["signals"]["signal_1_funding_event"]
    if sig1.get("confidence") in ("low",) and sig1.get("amount_usd"):
        amount = sig1["amount_usd"]
        millions = amount / 1_000_000
        return f"${millions:.0f}M" not in out and f"${amount:,}" not in out
    return True


def _check_no_seg4_low_ai(out: str, brief: dict) -> bool:
    sig5 = brief["signals"]["signal_5_ai_maturity"]
    icp = brief["signals"]["signal_6_icp_segment"]
    if sig5.get("score", 0) < 2 and icp.get("segment_number") == 4:
        return "ml platform" not in out.lower() and "agentic systems" not in out.lower()
    return True


def evaluate_output(output: str, brief: dict) -> bool:
    checks = [
        PASS_CRITERIA["no_offshore"](output),
        PASS_CRITERIA["no_hallucinated_amount"](output, brief),
        PASS_CRITERIA["no_segment4_low_ai"](output, brief),
    ]
    return all(checks)


def run_single_task(task: dict, config: dict) -> dict:
    import anthropic
    from langfuse import Langfuse

    import os
    os.environ["ASSERTION_THRESHOLD"] = str(config["assertion_threshold"])
    os.environ["ABSTENTION_THRESHOLD"] = str(config["abstention_threshold"])
    os.environ["CONFLICT_ABSTENTION"] = str(config["conflict_abstention"])

    # Re-import to pick up env changes
    import importlib
    import mechanism.confidence_gated_agent as cga
    importlib.reload(cga)

    brief = task["brief"]
    t0 = time.time()
    try:
        result = cga.compose_with_mechanism(brief, BASE_COMPETITOR, BASE_BENCH)
        latency_ms = (time.time() - t0) * 1000
        output = result.get("body", "") + " " + result.get("subject", "")
        passed = evaluate_output(output, brief)
        return {
            "task_id": task["task_id"],
            "scenario": task["scenario"],
            "passed": passed,
            "cost_usd": result.get("cost_usd", 0.0),
            "latency_ms": latency_ms,
            "trace_id": result.get("trace_id", ""),
            "mode_used": result.get("mode_used", ""),
            "variant_tag": result.get("variant_tag", ""),
            "abstain": result.get("abstain", False),
            "avg_confidence": result.get("avg_confidence", 0.0),
            "error": None
        }
    except Exception as e:
        latency_ms = (time.time() - t0) * 1000
        return {
            "task_id": task["task_id"],
            "scenario": task["scenario"],
            "passed": False,
            "cost_usd": 0.0,
            "latency_ms": latency_ms,
            "trace_id": "",
            "mode_used": "error",
            "variant_tag": "error",
            "abstain": False,
            "avg_confidence": 0.0,
            "error": str(e)
        }


def run_ablations(n_tasks: int = 20, config_names: list[str] | None = None):
    if config_names is None:
        config_names = list(ABLATION_CONFIGS.keys())

    tasks = HELD_OUT_TASKS[:n_tasks]
    all_condition_results = {}
    held_out_traces = []

    for config_name in config_names:
        config = ABLATION_CONFIGS[config_name]
        print(f"\n{'='*60}")
        print(f"Running config: {config_name}")
        print(f"  {config['description']}")
        print(f"  assertion_threshold={config['assertion_threshold']}")
        print(f"  abstention_threshold={config['abstention_threshold']}")
        print(f"  conflict_abstention={config['conflict_abstention']}")
        print(f"{'='*60}")

        task_results = []
        for i, task in enumerate(tasks):
            print(f"  Task {i+1:2d}/{len(tasks)}: {task['task_id']} ({task['scenario']})...", end=" ", flush=True)
            result = run_single_task(task, config)
            task_results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status}  ${result['cost_usd']:.4f}  {result['latency_ms']:.0f}ms  mode={result['mode_used']}")

            # Write to held_out_traces
            held_out_traces.append({
                "config_name": config_name,
                "task_id": task["task_id"],
                "scenario": task["scenario"],
                "trace_id": result["trace_id"],
                "passed": result["passed"],
                "cost_usd": result["cost_usd"],
                "latency_ms": result["latency_ms"],
                "mode_used": result["mode_used"],
                "variant_tag": result["variant_tag"],
                "abstain": result["abstain"],
                "avg_confidence": result["avg_confidence"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        passes = [1 if r["passed"] else 0 for r in task_results]
        costs = [r["cost_usd"] for r in task_results]
        latencies = [r["latency_ms"] for r in task_results]
        pass_mean = sum(passes) / len(passes)
        n = len(passes)
        # 95% CI using normal approximation
        se = math.sqrt(pass_mean * (1 - pass_mean) / n) if n > 1 else 0
        z = 1.96
        ci_lower = max(0.0, pass_mean - z * se)
        ci_upper = min(1.0, pass_mean + z * se)

        all_condition_results[config_name] = {
            "config_name": config_name,
            "description": config["description"],
            "n_tasks": n,
            "pass_at_1_mean": round(pass_mean, 4),
            "per_task_pass": passes,
            "ci_95_lower": round(ci_lower, 4),
            "ci_95_upper": round(ci_upper, 4),
            "cost_per_task_usd": round(sum(costs) / n, 6),
            "latency_p95_ms": round(sorted(latencies)[int(0.95 * n)], 1),
            "total_cost_usd": round(sum(costs), 4),
            "trace_ids": [r["trace_id"] for r in task_results if r["trace_id"]]
        }

        print(f"\n  → pass@1 = {pass_mean:.1%}  (95% CI: [{ci_lower:.1%}, {ci_upper:.1%}])")
        print(f"  → Total cost: ${sum(costs):.4f}  Avg latency p95: {sorted(latencies)[int(0.95*n)]:.0f}ms")

    # Write held_out_traces.jsonl
    traces_path = "held_out_traces.jsonl"
    with open(traces_path, "w") as f:
        for t in held_out_traces:
            f.write(json.dumps(t) + "\n")
    print(f"\nWrote {traces_path} ({len(held_out_traces)} lines)")

    # Compute deltas
    conditions_list = [all_condition_results[n] for n in config_names]
    baseline_passes = all_condition_results.get("baseline", {}).get("per_task_pass", [])
    v1_passes = all_condition_results.get("mechanism_v1", {}).get("per_task_pass", [])
    v2_passes = all_condition_results.get("mechanism_v2_strict", {}).get("per_task_pass", [])

    delta_a = {}
    delta_b = {}
    delta_c = {}
    if baseline_passes and v1_passes:
        delta_a = test_delta(baseline_passes, v1_passes, "baseline", "mechanism_v1")
    if v1_passes and v2_passes:
        delta_b = test_delta(v1_passes, v2_passes, "mechanism_v1", "mechanism_v2_strict")

    v1_mean = all_condition_results.get("mechanism_v1", {}).get("pass_at_1_mean", 0)
    delta_c = {
        "your_method": v1_mean,
        "published_reference": 0.42,
        "your_interim_baseline": 0.5067,
        "interpretation": (
            f"Your interim already exceeded published reference by +8.67pp. "
            f"Mechanism v1 achieves {v1_mean:.1%}, adding {v1_mean - 0.5067:+.1%} vs interim baseline."
        )
    }

    ablation_results = {
        "evaluation_date": datetime.now(timezone.utc).date().isoformat(),
        "held_out_slice": f"{n_tasks} tasks (held-out partition)",
        "interim_baseline_pass_at_1": 0.5067,
        "interim_baseline_notes": "50.67% on 150-conversation τ²-Bench suite from April 22 interim",
        "conditions": conditions_list,
        "delta_a": {
            "value": delta_a.get("delta", None),
            "p_value": delta_a.get("p_value", None),
            "significant": delta_a.get("significant", None),
            "interpretation": delta_a.get("interpretation", "")
        },
        "delta_b": {
            "value": delta_b.get("delta", None),
            "interpretation": delta_b.get("interpretation", "")
        },
        "delta_c": delta_c
    }

    out_path = "ablation_results.json"
    with open(out_path, "w") as f:
        json.dump(ablation_results, f, indent=2)
    print(f"Wrote {out_path}")

    print("\n" + "="*60)
    print("ABLATION SUMMARY")
    print("="*60)
    print(f"{'Config':<25} {'pass@1':>8} {'95% CI':>20} {'Cost/task':>10}")
    print("-"*65)
    for c in conditions_list:
        ci = f"[{c['ci_95_lower']:.1%}, {c['ci_95_upper']:.1%}]"
        print(f"{c['config_name']:<25} {c['pass_at_1_mean']:>8.1%} {ci:>20} ${c['cost_per_task_usd']:>8.4f}")

    if delta_a:
        print(f"\nDelta A (mechanism_v1 vs baseline): {delta_a.get('delta', 0):+.1%}")
        print(f"  {delta_a.get('interpretation', '')}")

    return ablation_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-tasks", type=int, default=20, help="Number of held-out tasks")
    parser.add_argument("--configs", help="Comma-separated config names to run")
    args = parser.parse_args()

    configs = [c.strip() for c in args.configs.split(",")] if args.configs else None
    run_ablations(n_tasks=args.n_tasks, config_names=configs)

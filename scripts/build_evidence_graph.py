import json
import os


def build_evidence_graph() -> dict:
    graph = {
        "version":      "1.0",
        "scenario":     "tenacious_consulting",
        "generated_at": "2026-04-22T20:00:00Z",
        "claims": [
            {
                "claim_id":            "C001",
                "claim_text":          "τ²-Bench pass@1 = X% (95% CI: X%–X%)",
                "grading_observable":  "reproduction_fidelity",
                "value":               None,
                "source_type":         "score_log",
                "source_ref":          "eval/score_log.json#run_001.pass_at_1_mean",
                "langfuse_trace_ids":  [],
                "recomputable":        True,
                "computation":         "mean(pass_results_5_trials_30_tasks)"
            },
            {
                "claim_id":            "C002",
                "claim_text":          "p50 latency = Xms across 20 email interactions",
                "grading_observable":  "cost_quality_pareto",
                "value":               None,
                "source_type":         "latency_log",
                "source_ref":          "eval/latency_results.json#p50_ms",
                "langfuse_trace_ids":  [],
                "recomputable":        True,
                "computation":         "median(latency_ms, n=20)"
            },
            {
                "claim_id":            "C003",
                "claim_text":          "p95 latency = Xms across 20 email interactions",
                "grading_observable":  "cost_quality_pareto",
                "value":               None,
                "source_type":         "latency_log",
                "source_ref":          "eval/latency_results.json#p95_ms",
                "langfuse_trace_ids":  [],
                "recomputable":        True,
                "computation":         "percentile(latency_ms, 0.95, n=20)"
            },
            {
                "claim_id":            "C004",
                "claim_text":          "Cost per prospect = $X — within $5.00 Tenacious target",
                "grading_observable":  "cost_quality_pareto",
                "value":               None,
                "unit":                "USD",
                "source_type":         "computed",
                "source_ref":          "eval/latency_results.json#cost_per_prospect_usd",
                "supporting_sources": [
                    "invoice_summary.json#total_llm_spend_usd",
                    "eval/trace_log.jsonl#email_compose_events"
                ],
                "langfuse_trace_ids":  [],
                "recomputable":        True,
                "computation":         "total_llm_spend_usd / 20_prospects",
                "thresholds": {
                    "target_usd":      5.00,
                    "kill_switch_usd": 8.00,
                    "penalty_above_usd": 8.00
                }
            },
            {
                "claim_id":            "C005",
                "claim_text":          "HubSpot contact created — all 22 fields non-null, enrichment timestamp current",
                "grading_observable":  "evidence_graph_integrity",
                "value":               None,
                "source_type":         "screenshot",
                "source_ref":          "screenshots/hubspot_contact_20260422.png",
                "langfuse_trace_ids":  [],
                "recomputable":        False,
                "computation":         "manual_screenshot_verification"
            },
            {
                "claim_id":            "C006",
                "claim_text":          "Cal.com booking created — both attendees listed",
                "grading_observable":  "evidence_graph_integrity",
                "value":               None,
                "source_type":         "screenshot",
                "source_ref":          "screenshots/calcom_booking_20260422.png",
                "langfuse_trace_ids":  [],
                "recomputable":        False,
                "computation":         "manual_screenshot_verification"
            },
            {
                "claim_id":            "C007",
                "claim_text":          "Six enrichment signals all producing output for test prospect",
                "grading_observable":  "evidence_graph_integrity",
                "value":               "novapay-technologies",
                "source_type":         "json_file",
                "source_ref":          "data/hiring_signal_brief_novapay.json",
                "langfuse_trace_ids":  [],
                "recomputable":        True,
                "computation":         "count(signals where output != null) == 6"
            }
        ]
    }

    # Populate values from generated files if they exist
    try:
        with open("eval/latency_results.json") as f:
            lr = json.load(f)
        for claim in graph["claims"]:
            if claim["claim_id"] == "C002":
                claim["value"] = lr.get("p50_ms")
                claim["claim_text"] = f"p50 latency = {lr['p50_ms']}ms across 20 email interactions"
            elif claim["claim_id"] == "C003":
                claim["value"] = lr.get("p95_ms")
                claim["claim_text"] = f"p95 latency = {lr['p95_ms']}ms across 20 email interactions"
            elif claim["claim_id"] == "C004":
                v = lr.get("cost_per_prospect_usd")
                claim["value"] = v
                within = "within" if lr.get("within_target") else "EXCEEDS"
                claim["claim_text"] = (
                    f"Cost per prospect = ${v} — {within} $5.00 Tenacious target"
                )
    except FileNotFoundError:
        pass

    try:
        with open("eval/score_log.json") as f:
            sl = json.load(f)
        run = sl["runs"][0]
        for claim in graph["claims"]:
            if claim["claim_id"] == "C001":
                pct = round(run["pass_at_1_mean"] * 100, 1)
                lo  = round(run["ci_95_lower"] * 100, 1)
                hi  = round(run["ci_95_upper"] * 100, 1)
                claim["value"] = run["pass_at_1_mean"]
                claim["claim_text"] = f"τ²-Bench pass@1 = {pct}% (95% CI: {lo}%–{hi}%)"
                claim["langfuse_trace_ids"] = run.get("langfuse_trace_ids", [])
    except FileNotFoundError:
        pass

    with open("evidence_graph.json", "w") as f:
        json.dump(graph, f, indent=2)

    print("evidence_graph.json written")
    return graph


if __name__ == "__main__":
    build_evidence_graph()

"""
Build failure_taxonomy.md and target_failure_mode.md from probe_results.json.
Run after: python probes/probe_runner.py

Usage: python probes/build_taxonomy.py
"""
import json
from pathlib import Path
from collections import defaultdict

CATEGORY_COSTS = {
    "bench_over_commitment": {"probes": ["P-009", "P-010", "P-011"], "avg_cost": 52000},
    "gap_over_claiming":     {"probes": ["P-030", "P-031", "P-032"], "avg_cost": 25000},
    "multi_thread_leakage":  {"probes": ["P-015", "P-016", "P-017"], "avg_cost": 31333},
    "icp_misclassification": {"probes": ["P-001", "P-002", "P-003", "P-004"], "avg_cost": 29000},
    "signal_reliability":    {"probes": ["P-027", "P-028", "P-029"], "avg_cost": 21667},
    "signal_over_claiming":  {"probes": ["P-005", "P-006", "P-007", "P-008"], "avg_cost": 17500},
    "tone_drift":            {"probes": ["P-012", "P-013", "P-014"], "avg_cost": 15667},
    "scheduling_edge_cases": {"probes": ["P-024", "P-025", "P-026"], "avg_cost": 11667},
    "dual_control_coordination": {"probes": ["P-021", "P-022", "P-023"], "avg_cost": 8667},
    "cost_pathology":        {"probes": ["P-018", "P-019", "P-020"], "avg_cost": 0.77},
}


def load_probe_results(path: str = "probes/probe_results.json") -> list[dict]:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found — run python probes/probe_runner.py first")
    with open(path) as f:
        return json.load(f)


def compute_category_stats(results: list[dict]) -> dict:
    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r["trigger_rate"])

    stats = {}
    for cat, info in CATEGORY_COSTS.items():
        rates = by_category.get(cat, [])
        avg_rate = sum(rates) / len(rates) if rates else 0.0
        avg_cost = info["avg_cost"]
        combined = avg_rate * avg_cost
        stats[cat] = {
            "probes": info["probes"],
            "avg_trigger_rate": avg_rate,
            "avg_business_cost": avg_cost,
            "combined_score": combined
        }
    return stats


def write_taxonomy(stats: dict, out_path: str = "probes/failure_taxonomy.md"):
    ranked = sorted(stats.items(), key=lambda x: x[1]["combined_score"], reverse=True)
    lines = [
        "# Failure Taxonomy — Tenacious Consulting Conversion Engine\n\n",
        "## Category Rankings (Frequency × Business Cost)\n\n",
        "| Category | Probes | Avg Trigger Rate | Avg Business Cost | Combined Score | Rank |\n",
        "|---|---|---|---|---|---|\n"
    ]
    for rank, (cat, s) in enumerate(ranked, 1):
        probes_str = ", ".join(s["probes"])
        cost_str = f"${s['avg_business_cost']:,.0f}" if s["avg_business_cost"] >= 1 else f"${s['avg_business_cost']:.2f}"
        combined_str = f"${s['combined_score']:,.0f}" if s["combined_score"] >= 1 else f"${s['combined_score']:.2f}"
        lines.append(
            f"| {cat} | {probes_str} | {s['avg_trigger_rate']:.1%} | {cost_str} | {combined_str} | {rank} |\n"
        )
    lines.append("\n**Combined Score** = Avg Trigger Rate × Avg Business Cost\n")
    lines.append("\n## Highest-ROI Failure → see target_failure_mode.md\n")

    Path(out_path).write_text("".join(lines))
    print(f"Wrote {out_path}")
    return ranked


def write_target(ranked: list, stats: dict, probe_results: list, out_path: str = "probes/target_failure_mode.md"):
    top_cat, top_stats = ranked[0]
    probe_ids = top_stats["probes"]
    probe_data = {r["probe_id"]: r for r in probe_results}

    avg_rate = top_stats["avg_trigger_rate"]
    avg_cost = top_stats["avg_business_cost"]
    combined = top_stats["combined_score"]
    per_1000 = combined * 10  # per outbound contact × 1000

    lines = [
        f"# Target Failure Mode\n\n",
        f"## Selected: {top_cat}\n\n",
        f"**Rank**: #1 by combined score (trigger_rate × business_cost)\n\n",
        f"### Why This Category\n",
        f"- Average trigger rate observed: {avg_rate:.1%}\n",
        f"- Average business cost per occurrence: ${avg_cost:,.0f}\n" if avg_cost >= 1 else f"- Average business cost per occurrence: ${avg_cost:.2f}\n",
        f"- Combined expected loss per 1,000 outbound contacts: ${per_1000:,.0f}\n\n" if per_1000 >= 1 else f"- Combined expected loss per 1,000 outbound contacts: ${per_1000:.2f}\n\n",
        f"### Business Cost Derivation\n",
        f"- Average deal ACV (talent outsourcing): $240K–$720K (Tenacious internal)\n",
        f"- Trigger rate observed: {avg_rate:.1%} across 10 trials per probe\n",
        f"- Estimated occurrences per 1,000 outbound contacts: {avg_rate * 1000:.0f}\n",
        f"- Expected value loss per occurrence: ${avg_cost:,.0f}\n" if avg_cost >= 1 else f"- Expected value loss per occurrence: ${avg_cost:.2f}\n",
        f"- **Total expected pipeline damage per 1,000 contacts: ${per_1000:,.0f}**\n\n" if per_1000 >= 1 else f"- **Total expected pipeline damage per 1,000 contacts: ${per_1000:.2f}**\n\n",
        f"### Why This Is Highest ROI to Fix\n",
        f"Combined score of ${combined:,.0f} beats all other categories. High trigger rate AND high business cost AND mechanically fixable within Act IV scope.\n\n",
        f"### Probe Results\n\n",
        f"| Probe | Trigger Rate | Business Cost | Trace IDs |\n",
        f"|---|---|---|---|\n"
    ]
    for pid in probe_ids:
        p = probe_data.get(pid, {})
        rate = p.get("trigger_rate", 0)
        cost = p.get("business_cost_usd", 0)
        tids = p.get("failure_trace_ids", [])[:2]
        tid_str = ", ".join(tids[:2]) + ("..." if len(tids) > 2 else "")
        cost_str = f"${cost:,.0f}" if cost >= 1 else f"${cost:.2f}"
        lines.append(f"| {pid} | {rate:.1%} | {cost_str} | {tid_str} |\n")

    lines += [
        f"\n### Proposed Mechanism (implemented in Act IV)\n",
        f"Confidence-gated phrasing + ICP abstention: when signal confidence is below threshold,\n",
        f"agent shifts from assertion to inquiry mode and abstains from segment-specific pitches.\n",
        f"\nSee: [mechanism/confidence_gated_agent.py](../mechanism/confidence_gated_agent.py)\n"
    ]

    Path(out_path).write_text("".join(lines))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    results = load_probe_results()
    stats = compute_category_stats(results)
    ranked = write_taxonomy(stats)
    write_target(ranked, stats, results)
    print("\nTop 3 failure categories by combined score:")
    for rank, (cat, s) in enumerate(ranked[:3], 1):
        print(f"  {rank}. {cat}: {s['avg_trigger_rate']:.1%} × ${s['avg_business_cost']:,.0f} = ${s['combined_score']:,.0f}")

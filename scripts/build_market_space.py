"""Market-space map (challenge stretch deliverable): apply AI-readiness
scoring to the full Crunchbase ODM sample and cluster into sector ×
company-size × readiness cells, scored for bench match against
tenacious_sales_data/seed/bench_summary.json.

Outputs:
    market_space.csv                one row per populated cell
    top_cells.md                    top cells ranked by combined score
    market_space_methodology.md     how scoring works + known error modes

Honesty note (documented in the methodology file too): population-level
AI-readiness here is a PROXY computed from firmographic fields present in
the ODM sample (industry labels, description keywords, BuiltWith tech tags,
funding recency) — not the full 6-input per-lead scoring, which needs job
posts and team pages the sample doesn't carry. Treat the map as a targeting
prior, refined per-lead by the real enrichment pipeline.

    python scripts/build_market_space.py
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ODM_PATH = BASE / "data" / "crunchbase_odm_sample.json"
BENCH_PATH = BASE / "tenacious_sales_data" / "seed" / "bench_summary.json"

AI_TECH = {
    "tensorflow", "pytorch", "databricks", "snowflake", "dbt", "ray",
    "weights & biases", "hugging face", "openai", "sagemaker", "mlflow",
    "vllm", "langchain",
}
AI_KEYWORDS = (
    "machine learning", " ml ", "artificial intelligence", " ai ", "ai-",
    "deep learning", "llm", "data science", "predictive", "computer vision",
    "nlp",
)
AI_INDUSTRIES = (
    "artificial intelligence", "machine learning", "analytics", "big data",
    "data", "predictive",
)

SIZE_BANDS = {
    "1-10": "1-10", "11-50": "11-50", "51-100": "51-200", "101-250": "51-200",
    "51-200": "51-200", "201-500": "201-1000", "251-500": "201-1000",
    "501-1000": "201-1000", "1001-5000": "1000+", "5001-10000": "1000+",
    "10001+": "1000+",
}

# Keywords mapping a company's public profile to Tenacious bench stacks.
STACK_KEYWORDS = {
    "python": ("python", "django", "fastapi", "saas", "api", "backend"),
    "go": ("go", "golang", "infrastructure", "cloud", "devops"),
    "data": ("data", "analytics", "etl", "warehouse", "snowflake", "dbt"),
    "ml": ("machine learning", "ai", "ml", "model", "intelligence"),
    "infra": ("kubernetes", "aws", "cloud", "platform", "infrastructure"),
}


def ai_readiness_proxy(record: dict) -> int:
    """0–3 proxy from fields available at population scale."""
    score = 0
    industries = (record.get("category_list") or "").lower()
    about = (record.get("about") or "").lower()
    tech = {t.lower() for t in record.get("tech_stack") or []}
    if any(k in industries for k in AI_INDUSTRIES):
        score += 1
    if any(k in f" {about} " for k in AI_KEYWORDS):
        score += 1
    if tech & AI_TECH:
        score += 1
    return min(score, 3)


def bench_match(record: dict, bench: dict) -> float:
    """Fraction of matched stacks weighted by available engineers."""
    text = " ".join([
        (record.get("category_list") or ""), (record.get("about") or ""),
        " ".join(record.get("tech_stack") or []),
    ]).lower()
    stacks = bench.get("stacks") or {}
    total = sum(s.get("available_engineers", 0) for s in stacks.values()) or 1
    matched = sum(
        s.get("available_engineers", 0)
        for name, s in stacks.items()
        if any(k in text for k in STACK_KEYWORDS.get(name, (name,)))
    )
    return round(matched / total, 3)


def recorded_funding_usd(record: dict) -> tuple[bool, int]:
    """(has a recorded funding event, its USD amount). The public ODM sample
    is a frozen snapshot with mostly old funding dates, so "funded in the
    last N months" would be empty — a live pilot swaps in fresh Crunchbase
    data and the per-lead pipeline applies the real 180-day window."""
    last = record.get("last_funding_at") or ""
    try:
        datetime.fromisoformat(last)
    except ValueError:
        return False, 0
    return True, int(record.get("last_funding_total_usd") or 0)


def main() -> int:
    records = json.loads(ODM_PATH.read_text())
    bench = json.loads(BENCH_PATH.read_text()) if BENCH_PATH.exists() else {}
    # Skip the curated fictional demo records — the map must be real data only.
    records = [r for r in records if "-uuid-" not in (r.get("uuid") or "")]

    cells: dict[tuple, dict] = defaultdict(lambda: {
        "population": 0, "funding_usd": 0, "funded_companies": 0,
        "bench_match_sum": 0.0,
    })
    for r in records:
        sector = (r.get("category_list") or "Unclassified").split(",")[0].strip() \
            or "Unclassified"
        size = SIZE_BANDS.get((r.get("num_employees_enum") or "").strip(), "unknown")
        readiness = ai_readiness_proxy(r)
        cell = cells[(sector, size, readiness)]
        cell["population"] += 1
        funded, funding = recorded_funding_usd(r)
        cell["funding_usd"] += funding
        cell["funded_companies"] += 1 if funded else 0
        cell["bench_match_sum"] += bench_match(r, bench)

    rows = []
    for (sector, size, readiness), c in cells.items():
        pop = c["population"]
        avg_match = c["bench_match_sum"] / pop
        # Combined score: cells with people to contact, money to spend,
        # meaningful AI openness, and work the bench can staff.
        combined = (
            min(pop, 20) / 20 * 0.25
            + (1 if c["funded_companies"] else 0) * 0.30
            + (readiness >= 1) * 0.20
            + avg_match * 0.25
        )
        rows.append({
            "sector": sector,
            "size_band": size,
            "ai_readiness_band": readiness,
            "population": pop,
            "funded_companies": c["funded_companies"],
            "avg_funding_usd": round(c["funding_usd"] / pop),
            "avg_bench_match": round(avg_match, 3),
            "combined_score": round(combined, 3),
        })
    rows.sort(key=lambda r: (-r["combined_score"], -r["population"]))

    csv_path = BASE / "market_space.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    top = [r for r in rows if r["population"] >= 3][:5]
    lines = [
        "# Top market-space cells for Tenacious outbound",
        "",
        f"Built from {len(records)} Crunchbase ODM records "
        f"(scripts/build_market_space.py; see market_space_methodology.md "
        "for scoring and known error modes).",
        "",
    ]
    for i, r in enumerate(top, 1):
        lines += [
            f"## {i}. {r['sector']} · {r['size_band']} employees · "
            f"AI-readiness {r['ai_readiness_band']}",
            "",
            f"{r['population']} companies, {r['funded_companies']} with a "
            f"recorded funding event (avg ${r['avg_funding_usd']:,}), "
            f"bench match {r['avg_bench_match']:.0%}, combined score "
            f"{r['combined_score']}.",
            "",
            "Recommendation: import this cell's companies as a campaign, let "
            "the enrichment service refine per-lead signals, and start at a "
            "conservative daily cap while warm-up ramps.",
            "",
        ]
    (BASE / "top_cells.md").write_text("\n".join(lines))
    print(f"Wrote {csv_path.name} ({len(rows)} cells) and top_cells.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

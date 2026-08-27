"""Generate hiring-signal + competitor-gap briefs by RUNNING the pipeline.

Usage:
    python scripts/export_hiring_brief.py [--company "Name"]

Default company: the same deterministic data-driven pick the demo seed uses
(most recently funded ODM company in the Tenacious ICP bands) — nothing
hand-chosen. Output: data/hiring_signal_brief_<slug>.json and
data/competitor_gap_brief_<slug>.json (run from the repo root — the
pipeline reads data/ paths relative to cwd).

The output is honestly labeled: several AI-maturity sub-signals and the
job-post fallback are deterministic proxies, not live lookups, so the brief
carries "synthetic": true — the engine's confidence gate then keeps
proxy-derived signals in inquiry mode (see enrichment/service.py, which
sets the same flag when serving this pipeline over HTTP).
"""
import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.live_sources import has_fabricated_sources
from enrichment.pipeline import enrich_company, generate_competitor_gap_brief

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from seed_demo_workspace import pick_demo_company  # noqa: E402

import argparse  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--company", default="",
                    help="company name (default: the data-driven demo pick)")
args = parser.parse_args()
COMPANY = args.company or pick_demo_company()["name"]
SLUG = "".join(c for c in COMPANY.lower() if c.isalnum() or c == " ").replace(" ", "_")

result = enrich_company(COMPANY)
signals = result.get("signals", {})
ai_score = int((signals.get("signal_5_ai_maturity") or {}).get("score", 0))
sector = (
    (result.get("firmographics") or {}).get("industry", "")
).split(",")[0].strip() or "fintech"
gap = generate_competitor_gap_brief(
    COMPANY, f"{SLUG.replace('_', '')}.example", ai_score, sector=sector
)

brief = {
    "company": COMPANY,
    "crunchbase_id": result.get("crunchbase_id", ""),
    "last_enriched_at": datetime.now(UTC).isoformat(),
    "synthetic": has_fabricated_sources(signals),  # tripwire: True only if any mock/proxy value slipped in
    "firmographics": result.get("firmographics", {}),
    "signals": signals,
}

os.makedirs("data", exist_ok=True)
with open(f"data/hiring_signal_brief_{SLUG}.json", "w") as f:
    json.dump(brief, f, indent=2)
with open(f"data/competitor_gap_brief_{SLUG}.json", "w") as f:
    json.dump(gap, f, indent=2)

print(f"Saved: data/hiring_signal_brief_{SLUG}.json (pipeline-generated)")
print(f"Saved: data/competitor_gap_brief_{SLUG}.json (pipeline-generated)")
for i, key in enumerate([
    "signal_1_funding_event", "signal_2_job_post_velocity",
    "signal_3_layoff_event", "signal_4_leadership_change",
    "signal_5_ai_maturity", "signal_6_icp_segment",
], 1):
    v = signals.get(key) or {}
    print(f"  Signal {i}: {'OK' if key in signals else 'MISSING'} "
          f"({key}, confidence={v.get('confidence')}, "
          f"source={v.get('source', '-')})")

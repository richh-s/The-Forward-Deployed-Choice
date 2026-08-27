"""Generate the NovaPay briefs by RUNNING the enrichment pipeline.

Writes data/hiring_signal_brief_novapay.json and
data/competitor_gap_brief_novapay.json from live pipeline output over the
Crunchbase ODM sample + layoffs.fyi data (run from the repo root — the
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

from enrichment.pipeline import enrich_company, generate_competitor_gap_brief

COMPANY = "NovaPay Technologies"

result = enrich_company(COMPANY)
signals = result.get("signals", {})
ai_score = int((signals.get("signal_5_ai_maturity") or {}).get("score", 0))
sector = (
    (result.get("firmographics") or {}).get("industry", "")
).split(",")[0].strip() or "fintech"
gap = generate_competitor_gap_brief(
    COMPANY, "novapay.example", ai_score, sector=sector
)

brief = {
    "company": COMPANY,
    "crunchbase_id": result.get("crunchbase_id", ""),
    "last_enriched_at": datetime.now(UTC).isoformat(),
    "synthetic": True,  # proxy-derived sub-signals — never assertion-grade
    "firmographics": result.get("firmographics", {}),
    "signals": signals,
}

os.makedirs("data", exist_ok=True)
with open("data/hiring_signal_brief_novapay.json", "w") as f:
    json.dump(brief, f, indent=2)
with open("data/competitor_gap_brief_novapay.json", "w") as f:
    json.dump(gap, f, indent=2)

print("Saved: data/hiring_signal_brief_novapay.json (pipeline-generated)")
print("Saved: data/competitor_gap_brief_novapay.json (pipeline-generated)")
for i, key in enumerate([
    "signal_1_funding_event", "signal_2_job_post_velocity",
    "signal_3_layoff_event", "signal_4_leadership_change",
    "signal_5_ai_maturity", "signal_6_icp_segment",
], 1):
    v = signals.get(key) or {}
    print(f"  Signal {i}: {'OK' if key in signals else 'MISSING'} "
          f"({key}, confidence={v.get('confidence')}, "
          f"source={v.get('source', '-')})")

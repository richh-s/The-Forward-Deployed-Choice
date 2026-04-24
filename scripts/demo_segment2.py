"""
Demo: Segment 2 routing with real layoffs.fyi data.

Shows the ICP classifier correctly routing a post-layoff + funded company
to Segment 2 (Cost Restructuring) rather than the naive Segment 1 (Recently Funded).

Company: Monte Carlo (data observability)
- Layoff: 30% of headcount, 29 days ago (real layoffs.fyi row, 2026-03-26)
- Funding: Series D, $25M, 106 days ago (Crunchbase ODM)
- Expected classification: Segment 2 (layoff + funding conflict → cost restructuring)

Run:
    python scripts/demo_segment2.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.pipeline import get_crunchbase_signal, get_layoff_signal, score_ai_maturity
from enrichment.icp_classifier import classify_icp_segment

COMPANY = "Monte Carlo"
PROSPECT_EMAIL = "cto@montecarlodata.com"


def banner(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def run_demo():
    banner("SEGMENT 2 DEMO — Real layoffs.fyi data")
    print(f"Company: {COMPANY}")
    print(f"Source:  layoffs.fyi CC-BY CSV + Crunchbase ODM")

    # ── Signal 1: Funding ────────────────────────────────────────
    banner("Signal 1 — Funding Event (Crunchbase ODM)")
    s1 = get_crunchbase_signal(COMPANY)
    print(json.dumps(s1, indent=2))

    # ── Signal 3: Layoff ─────────────────────────────────────────
    banner("Signal 3 — Layoff Event (real layoffs.fyi CSV)")
    s3 = get_layoff_signal(COMPANY)
    print(json.dumps(s3, indent=2))

    # ── Signal 5: AI maturity (stub — no job posts scraped) ─────
    s2 = {"engineering_roles": 8, "open_roles_total": 20,
          "delta_60d": "unknown", "confidence": "medium", "source": "demo_stub"}
    s5 = score_ai_maturity(COMPANY, s2)

    # ── Signal 4: Leadership change (not present for Monte Carlo) ─
    s4 = {"present": False, "confidence": "high", "source": "crunchbase_odm"}

    signals = {
        "signal_1_funding_event":     s1,
        "signal_2_job_post_velocity": s2,
        "signal_3_layoff_event":      s3,
        "signal_4_leadership_change": s4,
        "signal_5_ai_maturity":       s5,
    }

    # ── ICP Classification ────────────────────────────────────────
    banner("ICP Classification — Priority Rules")
    icp = classify_icp_segment(signals)
    signals["signal_6_icp_segment"] = icp
    print(json.dumps(icp, indent=2))

    # ── What a naive classifier would have said ──────────────────
    banner("Naive Classifier Comparison (what Segment 1 would have said)")
    print("  Naive: 'Fresh Series D funding → Segment 1 (Recently Funded)'")
    print("  Correct: Segment 2 overrides — cost pressure dominates.")
    print(f"  Rationale: {icp.get('rationale', '')}")
    print(f"  Conflict flag: {icp.get('conflict_flag', False)}")

    # ── Pitch language ────────────────────────────────────────────
    banner("Correct Pitch Language for Segment 2")
    print(f"  {icp.get('pitch_language', '')}")

    # ── Summary ───────────────────────────────────────────────────
    banner("Result")
    segment = icp.get("segment", "unknown")
    confidence = icp.get("confidence", 0)
    conflict = icp.get("conflict_flag", False)
    layoff_pct = s3.get("pct_workforce", 0)
    layoff_days = s3.get("days_ago", "?")
    funding_days = s1.get("days_ago", "?")
    funding_round = s1.get("round_type", "?")

    print(f"  Segment:       {segment}")
    print(f"  Confidence:    {confidence:.2f}")
    print(f"  Conflict flag: {conflict}")
    print(f"  Layoff:        {layoff_pct}% headcount, {layoff_days} days ago (layoffs.fyi)")
    print(f"  Funding:       {funding_round}, {funding_days} days ago (Crunchbase ODM)")
    print()
    assert segment == "segment_2_mid_market_restructure", (
        f"FAIL: expected segment_2, got {segment}"
    )
    print("  PASS: Segment 2 correctly selected over naive Segment 1.")


if __name__ == "__main__":
    run_demo()

"""
Run 20 synthetic prospects through compose_with_regeneration to produce a real
outreach trace log. Writes:

  eval/trace_log_outreach.jsonl   — one row per prospect (appended)
  eval/synthetic_run_summary.json — aggregate summary + gate-test results

Then runs scripts/compute_latency_percentiles.py against the new log and prints
the by-channel p50/p95.

Usage:
    LIVE_MODE=false python scripts/run_synthetic_traces.py
    LIVE_MODE=false python scripts/run_synthetic_traces.py --limit 5  # quick run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.email_pipeline import compose_with_regeneration  # noqa: E402

OUTREACH_TRACE_LOG = REPO_ROOT / "eval" / "trace_log_outreach.jsonl"
SUMMARY_PATH = REPO_ROOT / "eval" / "synthetic_run_summary.json"

# ── Bench fixtures ──────────────────────────────────────────────────────────

DEFAULT_BENCH = {
    "stacks": {
        "python":    {"available_engineers": 7,  "time_to_deploy_days": 7},
        "ml":        {"available_engineers": 5,  "time_to_deploy_days": 10},
        "data":      {"available_engineers": 9,  "time_to_deploy_days": 7},
        "infra":     {"available_engineers": 4,  "time_to_deploy_days": 14},
        "go":        {"available_engineers": 3,  "time_to_deploy_days": 14},
        "frontend":  {"available_engineers": 6,  "time_to_deploy_days": 7},
    },
    "total_engineers_on_bench": 34,
    "as_of": "2026-04-21",
}

EMPTY_INFRA_BENCH = {
    "stacks": {
        "python":   {"available_engineers": 7, "time_to_deploy_days": 7},
        "ml":       {"available_engineers": 5, "time_to_deploy_days": 10},
        "go":       {"available_engineers": 0, "time_to_deploy_days": 14},
        "infra":    {"available_engineers": 0, "time_to_deploy_days": 14},
    },
    "total_engineers_on_bench": 12,
    "as_of": "2026-04-21",
}

TINY_BENCH = {
    "stacks": {
        "python":   {"available_engineers": 4, "time_to_deploy_days": 7},
        "ml":       {"available_engineers": 0, "time_to_deploy_days": 10},
        "data":     {"available_engineers": 0, "time_to_deploy_days": 7},
    },
    "total_engineers_on_bench": 4,
    "as_of": "2026-04-21",
}

CONFIDENCE_LABEL = {1.0: "high", 0.7: "medium", 0.4: "low"}


def confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"


def make_brief(
    company: str,
    domain: str,
    *,
    recipient_first_name: str = "Maya",
    recipient_role: str = "VP Engineering",
    funding_stage: str | None = None,
    funding_amount_usd: int | None = None,
    funding_days_ago: int | None = None,
    open_roles_total: int = 0,
    engineering_roles: int = 0,
    open_roles_60d_ago: int = 0,
    layoff_pct: float | None = None,
    layoff_days_ago: int | None = None,
    leadership_role: str | None = None,
    leadership_days_ago: int | None = None,
    ai_maturity_score: int = 0,
    ai_maturity_confidence: str = "medium",
    primary_segment: int = 1,
    segment_confidence_label: str = "high",
    requested_stack: str | None = None,
    requested_headcount: int = 0,
    sector: str = "Fintech",
) -> dict:
    """Construct a hiring_signal_brief in the shape email_agent expects."""
    funding_signal = {
        "present": funding_stage is not None,
        "confidence": "high" if funding_stage else "low",
        "source": "crunchbase_odm",
    }
    if funding_stage:
        funding_signal.update({
            "days_ago": funding_days_ago,
            "amount_usd": funding_amount_usd,
            "round_type": funding_stage,
        })

    job_signal = {
        "open_roles_total": open_roles_total,
        "engineering_roles": engineering_roles,
        "delta_60d": f"+{engineering_roles - open_roles_60d_ago}" if engineering_roles >= open_roles_60d_ago else f"{engineering_roles - open_roles_60d_ago}",
        "open_roles_60d_ago": open_roles_60d_ago,
        "confidence": "high" if engineering_roles >= 5 else ("medium" if engineering_roles >= 3 else "low"),
        "source": "wellfound_scrape",
    }
    if engineering_roles < 5:
        job_signal["honesty_note"] = "weak signal — use inquiry phrasing, do not assert 'aggressive hiring'"

    layoff_signal = {
        "present": layoff_pct is not None,
        "confidence": "high" if layoff_pct is not None else "high",
        "source": "layoffs_fyi",
    }
    if layoff_pct is not None:
        layoff_signal.update({
            "days_ago": layoff_days_ago,
            "pct_workforce": layoff_pct,
        })

    leadership_signal = {
        "present": leadership_role is not None,
        "confidence": "medium" if leadership_role else "high",
        "source": "crunchbase_press",
    }
    if leadership_role:
        leadership_signal.update({
            "role": leadership_role,
            "days_ago": leadership_days_ago,
        })

    ai_signal = {
        "score": ai_maturity_score,
        "confidence": ai_maturity_confidence,
        "justification": [
            {"signal": "ai_adjacent_open_roles", "weight": "high",
             "detail": f"{max(0, ai_maturity_score)} open ML-adjacent roles inferred from Wellfound"},
            {"signal": "named_ai_leadership", "weight": "high",
             "detail": "Head of AI listed on team page" if ai_maturity_score >= 2 else "No named AI leadership"},
            {"signal": "modern_ml_stack", "weight": "low",
             "detail": "Snowflake + dbt inferred via BuiltWith"},
        ],
    }

    segment_label = {
        1: "Segment 1 — High Growth / Recently Funded",
        2: "Segment 2 — Mid-market Restructuring",
        3: "Segment 3 — New Engineering Leadership",
        4: "Segment 4 — AI / ML Capability Gap",
    }[primary_segment]

    icp_signal = {
        "segment": ["recently_funded", "restructuring", "new_leadership", "ai_capability_gap"][primary_segment - 1],
        "segment_number": primary_segment,
        "label": segment_label,
        "pitch_language": (
            "scale your AI team faster than in-house hiring" if primary_segment == 1 and ai_maturity_score >= 2
            else "stand up your first dedicated AI/ML function" if primary_segment == 1
            else "preserve delivery velocity through the restructure" if primary_segment == 2
            else "the new leader can ship a meaningful win in the first 90 days" if primary_segment == 3
            else "close the AI capability gap with managed senior delivery"
        ),
        "confidence": segment_confidence_label,
        "rationale": "synthetic test fixture",
    }

    brief = {
        "company": company,
        "crunchbase_id": company.lower().replace(" ", "-"),
        "last_enriched_at": "2026-05-01T10:00:00Z",
        "recipient": {
            "first_name": recipient_first_name,
            "role": recipient_role,
        },
        "firmographics": {
            "industry": sector,
            "funding_total_usd": funding_amount_usd or 0,
            "last_funding_type": funding_stage or "none",
        },
        "signals": {
            "signal_1_funding_event": funding_signal,
            "signal_2_job_post_velocity": job_signal,
            "signal_3_layoff_event": layoff_signal,
            "signal_4_leadership_change": leadership_signal,
            "signal_5_ai_maturity": ai_signal,
            "signal_6_icp_segment": icp_signal,
        },
        "bench_to_brief_match": {
            "required_stacks": [requested_stack] if requested_stack else (["ml", "python"] if ai_maturity_score >= 2 else ["python"]),
        },
    }
    if requested_stack:
        brief["requested_stack"] = requested_stack
        brief["requested_headcount"] = requested_headcount
    return brief


def make_competitor_brief(
    company: str,
    sector: str,
    prospect_score: int,
    peers: list[tuple[str, int]],
    gaps: list[dict],
) -> dict:
    return {
        "company": company,
        "sector": sector,
        "prospect_ai_maturity": prospect_score,
        "competitors_sampled": [{"name": n, "ai_maturity_score": s, "top_quartile": s >= 2} for n, s in peers],
        "gaps": gaps,
        "gap_quality_self_check": {
            "prospect_silent_but_sophisticated_risk": prospect_score <= 1,
        },
    }


def empty_competitor_brief(company: str, sector: str = "Fintech") -> dict:
    return {
        "company": company,
        "sector": sector,
        "prospect_ai_maturity": 0,
        "competitors_sampled": [],
        "gaps": [],
        "gap_quality_self_check": {"prospect_silent_but_sophisticated_risk": False},
    }


# ── 20 prospects ────────────────────────────────────────────────────────────

RECIPIENTS = [
    ("Maya",   "VP Engineering"),
    ("Tom",    "CTO"),
    ("Felix",  "Founder & CEO"),
    ("Priya",  "Head of Engineering"),
    ("Sam",    "VP Engineering"),
    ("Alex",   "CTO"),
    ("Jordan", "VP Engineering"),
    ("Riley",  "Head of Platform"),
    ("Cam",    "CTO"),
    ("Devi",   "VP Engineering"),
    ("Nia",    "Head of AI"),
    ("Owen",   "VP Engineering"),
    ("Mira",   "CTO"),
    ("Lex",    "Founder"),
    ("Kai",    "VP Engineering"),
    ("Ren",    "Head of Engineering"),
    ("June",   "VP Engineering"),
    ("Theo",   "CTO"),
    ("Sasha",  "Head of Platform"),
    ("Iris",   "VP Engineering"),
]


def build_prospects() -> list[dict]:
    """Return 20 distinct prospect scenarios."""
    out: list[dict] = []

    # SEGMENT 1 — recently funded
    out.append({
        "scenario_type": "segment1_high_signal_seriesA",
        "company": "SynthCo_01_AcornPay",
        "segment": 1,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "assertive, Segment 1 framing; reference Series A + 7 Python roles",
        "brief": make_brief(
            "AcornPay", "acornpay.com",
            funding_stage="Series A", funding_amount_usd=14_000_000, funding_days_ago=45,
            open_roles_total=10, engineering_roles=7, open_roles_60d_ago=2,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=1, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("AcornPay"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment1_high_signal_seriesB_data",
        "company": "SynthCo_02_LedgerLake",
        "segment": 1,
        "ai_maturity": 3,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "assertive Segment 1; data role focus",
        "brief": make_brief(
            "LedgerLake", "ledgerlake.io",
            funding_stage="Series B", funding_amount_usd=22_000_000, funding_days_ago=30,
            open_roles_total=8, engineering_roles=5, open_roles_60d_ago=1,
            ai_maturity_score=3, ai_maturity_confidence="high",
            primary_segment=1, segment_confidence_label="high", requested_stack="data",
        ),
        "competitor": empty_competitor_brief("LedgerLake"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment1_weak_signal",
        "company": "SynthCo_03_QuietBird",
        "segment": 1,
        "ai_maturity": 1,
        "signal_confidence": "low",
        "bench_edge_case": False,
        "expected_behavior": "interrogative phrasing; no 'aggressive hiring' assertion",
        "brief": make_brief(
            "QuietBird", "quietbird.app",
            funding_stage="Series A", funding_amount_usd=9_000_000, funding_days_ago=80,
            open_roles_total=3, engineering_roles=2, open_roles_60d_ago=2,
            ai_maturity_score=1, ai_maturity_confidence="low",
            primary_segment=1, segment_confidence_label="medium",
        ),
        "competitor": empty_competitor_brief("QuietBird"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment1_funded_and_layoff_conflict",
        "company": "SynthCo_04_RoughTide",
        "segment": 1,
        "ai_maturity": 2,
        "signal_confidence": "medium",
        "bench_edge_case": False,
        "expected_behavior": "ICP conflict; should acknowledge restructuring nuance, not pure 'scaling'",
        "brief": make_brief(
            "RoughTide", "roughtide.co",
            funding_stage="Series B", funding_amount_usd=18_000_000, funding_days_ago=50,
            open_roles_total=6, engineering_roles=4, open_roles_60d_ago=1,
            layoff_pct=0.08, layoff_days_ago=70,
            ai_maturity_score=2, ai_maturity_confidence="medium",
            primary_segment=1, segment_confidence_label="medium",
        ),
        "competitor": empty_competitor_brief("RoughTide"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment1_ai_maturity_zero",
        "company": "SynthCo_05_FernPay",
        "segment": 1,
        "ai_maturity": 0,
        "signal_confidence": "medium",
        "bench_edge_case": False,
        "expected_behavior": "'stand up first AI function' framing; no Segment 4 capability-gap pitch",
        "brief": make_brief(
            "FernPay", "fernpay.io",
            funding_stage="Series A", funding_amount_usd=12_000_000, funding_days_ago=40,
            open_roles_total=5, engineering_roles=3, open_roles_60d_ago=0,
            ai_maturity_score=0, ai_maturity_confidence="medium",
            primary_segment=1, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("FernPay"),
        "bench": DEFAULT_BENCH,
    })

    # SEGMENT 2 — restructuring
    out.append({
        "scenario_type": "segment2_layoff_still_hiring",
        "company": "SynthCo_06_PivotFi",
        "segment": 2,
        "ai_maturity": 1,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "preserve-velocity framing; backend roles emphasised",
        "brief": make_brief(
            "PivotFi", "pivotfi.com",
            layoff_pct=0.12, layoff_days_ago=45,
            open_roles_total=4, engineering_roles=4, open_roles_60d_ago=1,
            ai_maturity_score=1, ai_maturity_confidence="high",
            primary_segment=2, segment_confidence_label="high",
            requested_stack="python",
        ),
        "competitor": empty_competitor_brief("PivotFi"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment2_layoff_no_hires",
        "company": "SynthCo_07_DriftLogic",
        "segment": 2,
        "ai_maturity": 1,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "no capacity claim; question framing about delivery continuity",
        "brief": make_brief(
            "DriftLogic", "driftlogic.io",
            layoff_pct=0.20, layoff_days_ago=90,
            open_roles_total=0, engineering_roles=0, open_roles_60d_ago=2,
            ai_maturity_score=1, ai_maturity_confidence="high",
            primary_segment=2, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("DriftLogic"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment2_post_layoff_with_ai_angle",
        "company": "SynthCo_08_CinderRail",
        "segment": 2,
        "ai_maturity": 2,
        "signal_confidence": "medium",
        "bench_edge_case": False,
        "expected_behavior": "cost framing + AI continuity angle; no condescension",
        "brief": make_brief(
            "CinderRail", "cinderrail.dev",
            layoff_pct=0.15, layoff_days_ago=60,
            open_roles_total=3, engineering_roles=2, open_roles_60d_ago=4,
            ai_maturity_score=2, ai_maturity_confidence="medium",
            primary_segment=2, segment_confidence_label="medium",
        ),
        "competitor": empty_competitor_brief("CinderRail"),
        "bench": DEFAULT_BENCH,
    })

    # SEGMENT 3 — new leadership
    out.append({
        "scenario_type": "segment3_new_cto_only",
        "company": "SynthCo_09_OakChain",
        "segment": 3,
        "ai_maturity": 1,
        "signal_confidence": "medium",
        "bench_edge_case": False,
        "expected_behavior": "acknowledge new CTO appointment; offer to support 90-day plan",
        "brief": make_brief(
            "OakChain", "oakchain.io",
            leadership_role="CTO", leadership_days_ago=18,
            open_roles_total=2, engineering_roles=1, open_roles_60d_ago=1,
            ai_maturity_score=1, ai_maturity_confidence="medium",
            primary_segment=3, segment_confidence_label="medium",
        ),
        "competitor": empty_competitor_brief("OakChain"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment3_new_vp_with_ai_hiring",
        "company": "SynthCo_10_HarborStack",
        "segment": 3,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "leadership acknowledgement + AI capacity offer (gated on bench)",
        "brief": make_brief(
            "HarborStack", "harborstack.tech",
            leadership_role="VP Engineering", leadership_days_ago=60,
            open_roles_total=8, engineering_roles=5, open_roles_60d_ago=2,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=3, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("HarborStack"),
        "bench": DEFAULT_BENCH,
    })

    # SEGMENT 4 — capability gap
    out.append({
        "scenario_type": "segment4_mlops_gap",
        "company": "SynthCo_11_PalmFinance",
        "segment": 4,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "specific peer-MLOps gap; non-condescending phrasing",
        "brief": make_brief(
            "PalmFinance", "palmfinance.com",
            open_roles_total=10, engineering_roles=6, open_roles_60d_ago=1,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=4, segment_confidence_label="high",
        ),
        "competitor": make_competitor_brief(
            "PalmFinance", "Fintech", 2,
            peers=[("Stripe", 3), ("Plaid", 3), ("Brex", 3)],
            gaps=[
                {"finding": "Dedicated MLOps engineer role at all 3 peers; PalmFinance has none",
                 "confidence": "high",
                 "prospect_state": "0 MLOps-tagged roles in last 90 days",
                 "peer_evidence": "Stripe, Plaid, Brex public job posts"},
            ],
        ),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment4_competitor_head_of_ai",
        "company": "SynthCo_12_NovaWorks",
        "segment": 4,
        "ai_maturity": 3,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "very specific gap; mentions peer hire but stays research-toned",
        "brief": make_brief(
            "NovaWorks", "novaworks.ai",
            open_roles_total=15, engineering_roles=10, open_roles_60d_ago=4,
            ai_maturity_score=3, ai_maturity_confidence="high",
            primary_segment=4, segment_confidence_label="high",
        ),
        "competitor": make_competitor_brief(
            "NovaWorks", "Fintech", 3,
            peers=[("DirectCompetitor", 3)],
            gaps=[
                {"finding": "DirectCompetitor announced a Head of Applied AI 21 days ago",
                 "confidence": "high",
                 "prospect_state": "no public Head of AI named",
                 "peer_evidence": "press release 2026-04-10"},
            ],
        ),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "segment4_INVALID_low_maturity_must_be_blocked",
        "company": "SynthCo_13_LowSignal",
        "segment": 4,  # fed in deliberately wrong; gate must block Segment 4 framing
        "ai_maturity": 1,
        "signal_confidence": "low",
        "bench_edge_case": False,
        "expected_behavior": "Segment 4 framing must NOT appear; gate forces fallback",
        "brief": make_brief(
            "LowSignal", "lowsignal.dev",
            open_roles_total=2, engineering_roles=2, open_roles_60d_ago=1,
            ai_maturity_score=1, ai_maturity_confidence="low",
            primary_segment=4, segment_confidence_label="low",
        ),
        "competitor": make_competitor_brief(
            "LowSignal", "Fintech", 1,
            peers=[("Stripe", 3)],
            gaps=[{"finding": "Peer has Head of AI", "confidence": "medium",
                   "prospect_state": "no AI signal", "peer_evidence": "team page"}],
        ),
        "bench": DEFAULT_BENCH,
    })

    # BENCH EDGE CASES
    out.append({
        "scenario_type": "bench_overcommit_15_engineers_request",
        "company": "SynthCo_14_BigAsk",
        "segment": 1,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": True,
        "expected_behavior": "no specific headcount commitment; route to discovery call",
        "brief": make_brief(
            "BigAsk", "bigask.io",
            funding_stage="Series B", funding_amount_usd=30_000_000, funding_days_ago=20,
            open_roles_total=20, engineering_roles=15, open_roles_60d_ago=3,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=1, segment_confidence_label="high",
            requested_stack="ml", requested_headcount=15,
        ),
        "competitor": empty_competitor_brief("BigAsk"),
        "bench": TINY_BENCH,
    })
    out.append({
        "scenario_type": "bench_stack_mismatch_go_infra",
        "company": "SynthCo_15_RailStone",
        "segment": 1,
        "ai_maturity": 1,
        "signal_confidence": "medium",
        "bench_edge_case": True,
        "expected_behavior": "stack-mismatch flag (no Go/infra capacity); route to discovery call",
        "brief": make_brief(
            "RailStone", "railstone.io",
            funding_stage="Series A", funding_amount_usd=11_000_000, funding_days_ago=70,
            open_roles_total=6, engineering_roles=4, open_roles_60d_ago=1,
            ai_maturity_score=1, ai_maturity_confidence="medium",
            primary_segment=1, segment_confidence_label="medium",
            requested_stack="go", requested_headcount=3,
        ),
        "competitor": empty_competitor_brief("RailStone"),
        "bench": EMPTY_INFRA_BENCH,
    })

    # RE-ENGAGEMENT
    out.append({
        "scenario_type": "reengagement_new_layoff_signal",
        "company": "SynthCo_16_BackOnRadar",
        "segment": 2,
        "ai_maturity": 1,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "new layoff signal; no 'following up' / 'circling back'",
        "brief": make_brief(
            "BackOnRadar", "backonradar.com",
            layoff_pct=0.10, layoff_days_ago=14,
            open_roles_total=2, engineering_roles=2, open_roles_60d_ago=0,
            ai_maturity_score=1, ai_maturity_confidence="high",
            primary_segment=2, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("BackOnRadar"),
        "bench": DEFAULT_BENCH,
        "prior_thread": {
            "last_outbound_at": "2026-04-01T09:00:00Z",
            "last_outbound_subject": "Request: 15 min on your hiring",
            "reply_received": False,
        },
    })
    out.append({
        "scenario_type": "reengagement_after_warm_reply",
        "company": "SynthCo_17_WarmThread",
        "segment": 1,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "warm-reply re-engagement; new context, single ask",
        "brief": make_brief(
            "WarmThread", "warmthread.io",
            funding_stage="Series A", funding_amount_usd=10_000_000, funding_days_ago=50,
            open_roles_total=5, engineering_roles=4, open_roles_60d_ago=2,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=1, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("WarmThread"),
        "bench": DEFAULT_BENCH,
        "prior_thread": {
            "last_outbound_at": "2026-04-15T09:00:00Z",
            "last_outbound_subject": "Request: 15 min on your Series A hiring",
            "reply_received": True,
            "reply_excerpt": "Interested but slammed this week. Try me next month.",
        },
    })

    # TONE STRESS
    out.append({
        "scenario_type": "tone_stress_condescending_temptation",
        "company": "SynthCo_18_GapTrap",
        "segment": 4,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "competitor gap framed as research finding; never as failure",
        "brief": make_brief(
            "GapTrap", "gaptrap.com",
            open_roles_total=12, engineering_roles=8, open_roles_60d_ago=2,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=4, segment_confidence_label="high",
        ),
        "competitor": make_competitor_brief(
            "GapTrap", "Fintech", 2,
            peers=[("Stripe", 3), ("Plaid", 3)],
            gaps=[{"finding": "Both peers have shipped public AI products in last 6 months",
                   "confidence": "high",
                   "prospect_state": "no public AI product launch detected",
                   "peer_evidence": "press releases"}],
        ),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "tone_stress_overconfidence_temptation",
        "company": "SynthCo_19_FaintHum",
        "segment": 1,
        "ai_maturity": 1,
        "signal_confidence": "low",
        "bench_edge_case": False,
        "expected_behavior": "honest marker: refuse to assert; ask instead",
        "brief": make_brief(
            "FaintHum", "fainthum.dev",
            funding_stage="Series A", funding_amount_usd=8_000_000, funding_days_ago=110,
            open_roles_total=2, engineering_roles=1, open_roles_60d_ago=2,
            ai_maturity_score=1, ai_maturity_confidence="low",
            primary_segment=1, segment_confidence_label="low",
        ),
        "competitor": empty_competitor_brief("FaintHum"),
        "bench": DEFAULT_BENCH,
    })
    out.append({
        "scenario_type": "tone_stress_clean_first_pass_expected",
        "company": "SynthCo_20_CleanShot",
        "segment": 1,
        "ai_maturity": 2,
        "signal_confidence": "high",
        "bench_edge_case": False,
        "expected_behavior": "all 5 markers should pass first attempt with no regeneration",
        "brief": make_brief(
            "CleanShot", "cleanshot.io",
            funding_stage="Series B", funding_amount_usd=20_000_000, funding_days_ago=25,
            open_roles_total=12, engineering_roles=8, open_roles_60d_ago=2,
            ai_maturity_score=2, ai_maturity_confidence="high",
            primary_segment=1, segment_confidence_label="high",
        ),
        "competitor": empty_competitor_brief("CleanShot"),
        "bench": DEFAULT_BENCH,
    })

    # Inject distinct recipient names so the composer doesn't emit [First Name]
    # placeholders. Each prospect gets a unique (name, role) pair.
    for i, prospect in enumerate(out):
        first_name, role = RECIPIENTS[i % len(RECIPIENTS)]
        prospect["brief"]["recipient"] = {"first_name": first_name, "role": role}

    return out


# ── Gate-test heuristics (computed AFTER traces are written) ────────────────

INTERROGATIVE_PATTERNS = re.compile(r"\?|\bis\b.+\?|\bare\b.+\?|\bwould\b|\bcurious\b|\bopen to\b", re.IGNORECASE)
SEGMENT_4_TELL = re.compile(r"capability gap|catching up|behind (?:the curve|peers)|falling behind|ai maturity (?:is|score)", re.IGNORECASE)
COMMITMENT_TELL = re.compile(r"\b(\d+)\s+(?:senior\s+)?(?:engineers?|devs?)\b|\bcan deliver\b|\bcommit to\b", re.IGNORECASE)
FOLLOWUP_BANNED = re.compile(r"\b(?:following up|circling back|just checking in|per my last email|quick (?:question|chat))\b", re.IGNORECASE)


def evaluate_gate_tests(traces: list[dict]) -> dict:
    """Compute four binary gate-test results from the trace list."""
    results = {}

    # 1) Segment 4 must be blocked at AI maturity 1 (SynthCo_13)
    target = next((t for t in traces if t["scenario_type"] == "segment4_INVALID_low_maturity_must_be_blocked"), None)
    if target and target["actual_status"] != "error":
        text = (target["subject"] + " " + target.get("body", "")).lower()
        results["segment_4_blocked_at_maturity_1"] = "PASS" if not SEGMENT_4_TELL.search(text) else "FAIL"
    else:
        results["segment_4_blocked_at_maturity_1"] = "N/A (scenario errored)"

    # 2) Bench over-commitment correctly rerouted (SynthCo_14 + SynthCo_15)
    bench_targets = [t for t in traces if t["scenario_type"] in (
        "bench_overcommit_15_engineers_request", "bench_stack_mismatch_go_infra"
    )]
    if bench_targets:
        commits = []
        for t in bench_targets:
            text = t.get("body", "")
            m = COMMITMENT_TELL.search(text)
            commits.append(bool(m and "engineer" in text.lower()))
        results["bench_overcommit_rerouted"] = "PASS" if not any(commits) else "FAIL"
    else:
        results["bench_overcommit_rerouted"] = "N/A"

    # 3) Weak signal used interrogative phrasing (SynthCo_03 + SynthCo_19)
    weak_targets = [t for t in traces if t["scenario_type"] in (
        "segment1_weak_signal", "tone_stress_overconfidence_temptation"
    )]
    if weak_targets:
        oks = []
        for t in weak_targets:
            text = t.get("body", "")
            oks.append(bool(INTERROGATIVE_PATTERNS.search(text)))
        results["weak_signal_used_interrogative"] = "PASS" if all(oks) else "FAIL"
    else:
        results["weak_signal_used_interrogative"] = "N/A"

    # 4) Re-engagement added new content, no banned follow-up phrases (SynthCo_16)
    target = next((t for t in traces if t["scenario_type"] == "reengagement_new_layoff_signal"), None)
    if target and target["actual_status"] != "error":
        text = target.get("body", "")
        no_banned = not FOLLOWUP_BANNED.search(text)
        has_layoff = "layoff" in text.lower() or "10%" in text or "two weeks" in text.lower() or "14 days" in text.lower()
        results["reengagement_added_new_content"] = "PASS" if (no_banned and has_layoff) else "FAIL"
    else:
        results["reengagement_added_new_content"] = "N/A"

    return results


# ── Runner ──────────────────────────────────────────────────────────────────

def run_one(prospect: dict) -> dict:
    start = time.time()
    try:
        result = compose_with_regeneration(
            hiring_signal_brief=prospect["brief"],
            competitor_gap_brief=prospect["competitor"],
            bench_summary=prospect["bench"],
            prior_thread=prospect.get("prior_thread"),
            pricing_in_scope=False,
        )
    except Exception as e:
        return {
            "trace_id": f"outreach_{prospect['company']}_{int(start*1000)}",
            "channel": "email",
            "scenario_type": prospect["scenario_type"],
            "company": prospect["company"],
            "segment": prospect["segment"],
            "ai_maturity": prospect["ai_maturity"],
            "signal_confidence": prospect["signal_confidence"],
            "bench_edge_case": prospect["bench_edge_case"],
            "expected_behavior": prospect["expected_behavior"],
            "actual_status": "error",
            "attempts_needed": 0,
            "subject": "",
            "body": "",
            "word_count": 0,
            "final_score": 0,
            "marker_scores": {},
            "failed_markers": [],
            "roast_verdict": "SKIPPED",
            "latency_ms": int((time.time() - start) * 1000),
            "cost_usd": 0.0,
            "langfuse_trace_id": None,
            "model_used": "unknown",
            "judge_model_used": "unknown",
            "error": f"{type(e).__name__}: {e}",
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
        }

    elapsed_ms = int((time.time() - start) * 1000)
    usage = result.get("usage") or {}
    in_tok = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)
    cost_usd = round(in_tok * 3e-6 + out_tok * 1.5e-5, 6)
    body = result.get("body", "")
    marker_scores = result.get("final_scores") or {}
    final_score = min(marker_scores.values()) if marker_scores else 0

    return {
        "trace_id": f"outreach_{prospect['company']}_{int(start*1000)}",
        "channel": "email",
        "scenario_type": prospect["scenario_type"],
        "company": prospect["company"],
        "segment": prospect["segment"],
        "ai_maturity": prospect["ai_maturity"],
        "signal_confidence": prospect["signal_confidence"],
        "bench_edge_case": prospect["bench_edge_case"],
        "expected_behavior": prospect["expected_behavior"],
        "actual_status": result["status"],
        "attempts_needed": result["attempts"],
        "subject": result["subject"],
        "body": body,
        "word_count": len(body.split()),
        "final_score": final_score,
        "marker_scores": marker_scores,
        "failed_markers": result["failed_markers"],
        "roast_verdict": result["roast_verdict"],
        "latency_ms": elapsed_ms,
        "cost_usd": cost_usd,
        "langfuse_trace_id": result.get("langfuse_trace_id"),
        "model_used": result["model_used"],
        "judge_model_used": result["judge_model_used"],
        "reason": result.get("reason"),
        "timestamp": dt.datetime.utcnow().isoformat() + "Z",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 20 synthetic prospect outreach traces")
    parser.add_argument("--limit", type=int, default=None, help="Run only N prospects (debug)")
    parser.add_argument("--output", default=str(OUTREACH_TRACE_LOG), help="Path to outreach trace log")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prospects = build_prospects()
    if args.limit:
        prospects = prospects[: args.limit]

    print(f"=== SYNTHETIC TRACE RUN — {len(prospects)} prospect(s) ===")
    print(f"  LIVE_MODE: {os.environ.get('LIVE_MODE', 'false')} (must be 'false' for sink routing)")
    print(f"  trace log: {output_path}")
    print()

    traces: list[dict] = []
    for i, p in enumerate(prospects, 1):
        print(f"[{i:02d}/{len(prospects)}] {p['company']} ({p['scenario_type']}) ...", flush=True)
        row = run_one(p)
        traces.append(row)
        with output_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        status_label = row["actual_status"].upper()
        print(
            f"     status={status_label} attempts={row['attempts_needed']} "
            f"roast={row['roast_verdict']} subj={row['subject'][:60]!r} "
            f"words={row['word_count']} latency_ms={row['latency_ms']} cost=${row['cost_usd']:.4f}"
        )

    # Aggregate
    n = len(traces)
    sent = [t for t in traces if t["actual_status"] == "sent"]
    escalated = [t for t in traces if t["actual_status"] == "escalated"]
    roast_failed = [t for t in traces if t["actual_status"] == "roast_fail"]
    errored = [t for t in traces if t["actual_status"] == "error"]
    first_pass = [t for t in sent if t["attempts_needed"] == 1]
    regen = [t for t in sent if t["attempts_needed"] > 1]
    avg_attempts = round(sum(t["attempts_needed"] for t in traces) / max(n, 1), 2)
    avg_latency = int(sum(t["latency_ms"] for t in traces) / max(n, 1))
    avg_cost = round(sum(t["cost_usd"] for t in traces) / max(n, 1), 4)
    pass_rate = round(len(sent) / max(n, 1) * 100, 1)

    gate_results = evaluate_gate_tests(traces)

    print()
    print("=== SYNTHETIC TRACE RUN SUMMARY ===")
    print(f"Total traces: {n}")
    print(f"Passed on first attempt: {len(first_pass)}")
    print(f"Required regeneration: {len(regen)}")
    print(f"Escalated to human: {len(escalated)}")
    print(f"Roast test failures: {len(roast_failed)}")
    print(f"Errored: {len(errored)}")
    print(f"Average attempts: {avg_attempts}")
    print(f"Average latency: {avg_latency}ms")
    print(f"Average cost: ${avg_cost:.4f}")
    print(f"Pass rate: {pass_rate}%")
    print()
    print("Gate tests:")
    for k, v in gate_results.items():
        print(f"  - {k}: {v}")

    summary = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "total_traces": n,
        "passed_on_first_attempt": len(first_pass),
        "required_regeneration": len(regen),
        "escalated_to_human": len(escalated),
        "roast_test_failures": len(roast_failed),
        "errored": len(errored),
        "average_attempts": avg_attempts,
        "average_latency_ms": avg_latency,
        "average_cost_usd": avg_cost,
        "pass_rate_pct": pass_rate,
        "gate_tests": gate_results,
        "trace_log_path": str(output_path),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {SUMMARY_PATH}")

    # Now compute latency percentiles on the new trace log
    print("\n=== LATENCY PERCENTILES (by channel) ===")
    pct_script = REPO_ROOT / "scripts" / "compute_latency_percentiles.py"
    pct_out = REPO_ROOT / "eval" / "latency_percentiles_outreach.json"
    try:
        proc = subprocess.run(
            [sys.executable, str(pct_script), str(output_path), "--output", str(pct_out)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        print(proc.stdout, end="")
        if proc.returncode != 0:
            print(proc.stderr, end="")
    except Exception as e:
        print(f"  [warn] percentile script failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

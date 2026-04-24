"""
ICP segment classifier.
Implements the official priority rules from tenacious_sales_data/seed/icp_definition.md.

Priority order (first match wins):
  1. Layoff (≤120 days) AND fresh funding    → Segment 2
  2. New CTO/VP Eng (≤90 days)               → Segment 3
  3. Capability gap AND AI-readiness ≥ 2     → Segment 4
  4. Fresh funding (≤180 days)               → Segment 1
  5. Otherwise                               → abstain
"""

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}


def _conf_float(conf_value) -> float:
    if isinstance(conf_value, float):
        return conf_value
    return CONFIDENCE_MAP.get(str(conf_value).lower(), 0.4)


def classify_icp_segment(signals: dict) -> dict:
    """
    Signal 6 is always DERIVED from signals 1-5 using official icp_definition.md rules.
    Never fetched externally. Returns confidence as float in [0, 1].
    """
    s1 = signals.get("signal_1_funding_event", {})
    s2 = signals.get("signal_2_job_post_velocity", {})
    s3 = signals.get("signal_3_layoff_event", {})
    s4 = signals.get("signal_4_leadership_change", {})
    s5 = signals.get("signal_5_ai_maturity", {})

    # Extract signal values
    has_funding = bool(s1.get("amount_usd") or s1.get("present"))
    funding_days = s1.get("days_ago", 9999)
    funding_round = s1.get("round", s1.get("round_type", "")).lower()

    # Segment 1 gate: early-stage only (Series A/B or Seed)
    fresh_funding = (
        has_funding
        and funding_days <= 180
        and any(r in funding_round for r in ["series a", "series b", "seed", "a", "b"])
    )

    # Segment 2 gate: any venture-backed round within 180 days.
    # Late-stage companies (C/D/E/F) that also lay off are classic cost-restructuring targets.
    _VENTURE_STAGES = {"series a", "series b", "series c", "series d",
                       "series e", "series f", "seed", "venture", "growth"}
    fresh_funding_any_stage = (
        has_funding
        and funding_days <= 180
        and any(vs in funding_round for vs in _VENTURE_STAGES)
    )

    has_layoff = (
        s3.get("layoff_detected", False)
        or s3.get("present", False)
    )
    layoff_days = s3.get("days_ago", 9999)
    layoff_pct = s3.get("pct_workforce", s3.get("percentage_cut", 0)) or 0
    recent_layoff = has_layoff and layoff_days <= 120

    has_leadership = (
        s4.get("change_detected", False)
        or s4.get("present", False)
    )
    leadership_days = s4.get("days_ago", 9999)
    leadership_role = s4.get("role", "").upper()
    recent_leadership = (
        has_leadership
        and leadership_days <= 90
        and any(r in leadership_role for r in ["CTO", "VP ENG", "VP ENGINEERING"])
    )

    ai_score = s5.get("score", 0)
    open_roles = s2.get("engineering_roles", 0)

    # Segment 4 gate: repeated specialist postings open 60+ days or capability gap signal
    # For outbound, ai_maturity >= 2 is the minimum gate
    has_capability_gap = ai_score >= 2

    # Compute per-signal confidence
    conf_s1 = _conf_float(s1.get("confidence", "low"))
    conf_s3 = _conf_float(s3.get("confidence", "low"))
    conf_s4 = _conf_float(s4.get("confidence", "low"))
    conf_s5 = _conf_float(s5.get("confidence", "low"))

    # ── Priority 1: Layoff (≤120 days) AND fresh funding → Segment 2 ───────
    # icp_definition.md: "cost pressure dominates the buying window"
    # Layoff ≤40% is required; above that, company is in survival mode.
    # Any venture round qualifies (not just A/B): Series D companies that cut headcount
    # while holding runway are the archetypal Segment 2 target.
    if recent_layoff and fresh_funding_any_stage and layoff_pct <= 40:
        seg_confidence = min(conf_s1, conf_s3)
        conflict_flag = True  # funding + layoff is an inherent conflict signal
        return {
            "segment": "segment_2_mid_market_restructure",
            "segment_number": 2,
            "label": "Segment 2 — Mid-market / Cost Restructuring",
            "pitch_language": (
                "preserve your AI delivery capacity while reshaping cost structure"
                if ai_score >= 2
                else "maintain platform delivery velocity through the restructure"
            ),
            "confidence": round(seg_confidence, 3),
            "rationale": (
                f"Layoff {layoff_days}d ago ({layoff_pct}% of headcount). "
                f"Fresh funding ({funding_round}, {funding_days}d ago). "
                "Rule 1: cost pressure dominates — Segment 2 overrides Segment 1."
            ),
            "conflict_flag": conflict_flag,
            "conflict_note": "Layoff + fresh funding conflict detected. Segment 2 priority per icp_definition.md Rule 1.",
            "all_matched_segments": ["segment_2_mid_market_restructure", "segment_1_series_a_b"],
            "honesty_flag": "conflicting_segment_signals" if conf_s3 < 0.6 or conf_s1 < 0.6 else None
        }

    # Also Segment 2 when there's a layoff without fresh funding
    if recent_layoff and not fresh_funding_any_stage and open_roles >= 3 and layoff_pct <= 40:
        seg_confidence = conf_s3
        if seg_confidence < 0.6:
            return _abstain(reason="layoff signal below confidence threshold 0.6")
        return {
            "segment": "segment_2_mid_market_restructure",
            "segment_number": 2,
            "label": "Segment 2 — Mid-market / Cost Restructuring",
            "pitch_language": (
                "preserve your AI delivery capacity while reshaping cost structure"
                if ai_score >= 2
                else "maintain platform delivery velocity through the restructure"
            ),
            "confidence": round(seg_confidence, 3),
            "rationale": (
                f"Layoff {layoff_days}d ago ({layoff_pct}% of headcount). "
                f"No fresh funding. {open_roles} open roles remain (active delivery)."
            ),
            "conflict_flag": False,
            "conflict_note": "",
            "all_matched_segments": ["segment_2_mid_market_restructure"]
        }

    # ── Priority 2: New CTO/VP Eng (≤90 days) → Segment 3 ─────────────────
    if recent_leadership:
        seg_confidence = conf_s4
        if seg_confidence < 0.6:
            return _abstain(reason="leadership change signal below confidence threshold 0.6")
        return {
            "segment": "segment_3_leadership_transition",
            "segment_number": 3,
            "label": "Segment 3 — Engineering Leadership Transition",
            "pitch_language": (
                "new engineering leaders reassess vendor mix in their first 90 days — "
                "congratulations on the appointment; this is that window"
            ),
            "confidence": round(seg_confidence, 3),
            "rationale": (
                f"New {leadership_role} appointed {leadership_days}d ago. "
                "Vendor reassessment window open. "
                "AI maturity score does not shift Segment 3 pitch."
            ),
            "conflict_flag": fresh_funding,  # fresh funding alongside leadership = two signals
            "conflict_note": (
                "Fresh funding also present — consider Segment 1 language after Segment 3 intro."
                if fresh_funding else ""
            ),
            "all_matched_segments": (
                ["segment_3_leadership_transition", "segment_1_series_a_b"]
                if fresh_funding else ["segment_3_leadership_transition"]
            )
        }

    # ── Priority 3: Capability gap AND AI-readiness ≥ 2 → Segment 4 ───────
    if has_capability_gap:
        seg_confidence = conf_s5
        if seg_confidence < 0.6:
            return _abstain(reason="AI maturity signal below confidence threshold 0.6")
        return {
            "segment": "segment_4_specialized_capability",
            "segment_number": 4,
            "label": "Segment 4 — Specialized Capability Gap",
            "pitch_language": (
                "project-based consulting for ML platform build, "
                "agentic systems, or data-contracts architecture"
            ),
            "confidence": round(seg_confidence, 3),
            "rationale": (
                f"AI maturity score {ai_score}/3 clears Segment 4 gate (≥2 required). "
                "Pitch specialized capability, not headcount."
            ),
            "conflict_flag": False,
            "conflict_note": "",
            "all_matched_segments": ["segment_4_specialized_capability"]
        }

    # ── Priority 4: Fresh funding (≤180 days) → Segment 1 ─────────────────
    if fresh_funding and open_roles >= 5:
        seg_confidence = conf_s1
        if seg_confidence < 0.6:
            return _abstain(reason="funding signal below confidence threshold 0.6")
        return {
            "segment": "segment_1_series_a_b",
            "segment_number": 1,
            "label": "Segment 1 — Recently Funded Series A/B",
            "pitch_language": (
                "scale your AI team faster than in-house hiring can support"
                if ai_score >= 2
                else "stand up your first dedicated engineering function"
            ),
            "confidence": round(seg_confidence, 3),
            "rationale": (
                f"{funding_round.title()} closed {funding_days}d ago. "
                f"No layoff. {open_roles} open engineering roles. "
                f"AI maturity {ai_score}/3 sets pitch language."
            ),
            "conflict_flag": False,
            "conflict_note": "",
            "all_matched_segments": ["segment_1_series_a_b"]
        }

    # ── Priority 4b: Fresh funding but < 5 open roles ─────────────────────
    if fresh_funding and open_roles < 5:
        return _abstain(
            reason=(
                f"Fresh funding detected but only {open_roles} open engineering roles "
                "(requires ≥5 for Segment 1 qualification per icp_definition.md)"
            )
        )

    # ── Priority 5: Abstain ───────────────────────────────────────────────
    return _abstain(reason="No qualifying signal for any segment")


def _abstain(reason: str) -> dict:
    return {
        "segment": "abstain",
        "segment_number": 0,
        "label": "Abstain — generic exploratory email only",
        "pitch_language": "generic exploratory inquiry — no segment-specific pitch",
        "confidence": 0.0,
        "rationale": reason,
        "conflict_flag": False,
        "conflict_note": "",
        "all_matched_segments": []
    }

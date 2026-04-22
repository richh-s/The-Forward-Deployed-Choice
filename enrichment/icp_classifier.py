def classify_icp_segment(signals: dict) -> dict:
    """
    Signal 6 is always derived from signals 1-5.
    It is never fetched from an external source.
    Priority: Segment 1 > 2 > 3 > 4. First match wins.
    Conflict flagged when multiple segments match.
    """
    s1 = signals["signal_1_funding_event"]
    s2 = signals["signal_2_job_post_velocity"]
    s3 = signals["signal_3_layoff_event"]
    s4 = signals["signal_4_leadership_change"]
    s5 = signals["signal_5_ai_maturity"]

    matched = []

    # Segment 1 — High Growth / Recently Funded
    # Trigger: Series A or B within 180 days, no layoff
    if (
        s1["present"]
        and s1["days_ago"] <= 180
        and s1["round_type"] in ["Series A", "Series B"]
        and not s3["present"]
    ):
        matched.append({
            "segment": "recently_funded",
            "segment_number": 1,
            "label": "Segment 1 — High Growth / Recently Funded",
            "pitch_language": (
                "scale your AI team faster than in-house hiring"
                if s5["score"] >= 2
                else "stand up your first dedicated engineering function"
            ),
            "confidence": s1["confidence"],
            "rationale": (
                f"{s1['round_type']} closed {s1['days_ago']}d ago. "
                f"No layoff. {s2['engineering_roles']} open engineering "
                f"roles. AI maturity {s5['score']}/3 sets pitch language."
            )
        })

    # Segment 2 — Post-Layoff / Cost Restructuring
    # Trigger: layoff within 120 days
    if s3["present"] and s3.get("days_ago", 999) <= 120:
        matched.append({
            "segment": "mid_market_restructuring",
            "segment_number": 2,
            "label": "Segment 2 — Post-Layoff / Cost Restructuring",
            "pitch_language": (
                "replace higher-cost roles with a dedicated engineering "
                "team without cutting delivery output"
            ),
            "confidence": s3["confidence"],
            "rationale": (
                f"Layoff {s3.get('days_ago', '?')}d ago. "
                "Cost restructuring pitch applies. "
                "Do NOT use Segment 1 scale language."
            )
        })

    # Segment 3 — New Engineering Leadership
    # Trigger: new CTO or VP Eng within 90 days
    if (
        s4["present"]
        and s4.get("days_ago", 999) <= 90
        and s4.get("role", "") in ["CTO", "VP Engineering", "VP Eng"]
    ):
        matched.append({
            "segment": "engineering_leadership_transition",
            "segment_number": 3,
            "label": "Segment 3 — New Engineering Leadership",
            "pitch_language": (
                "new engineering leaders reassess vendor mix in their "
                "first 90 days — this is that window"
            ),
            "confidence": s4["confidence"],
            "rationale": (
                f"New {s4['role']} appointed {s4['days_ago']}d ago. "
                "Vendor reassessment window open. "
                "AI maturity score does not affect this pitch."
            )
        })

    # Segment 4 — AI / ML Capability Gap
    # Hard gate: NEVER pitch this below ai_maturity_score 2
    if s5["score"] >= 2:
        matched.append({
            "segment": "specialized_capability_gap",
            "segment_number": 4,
            "label": "Segment 4 — AI / ML Capability Gap",
            "pitch_language": (
                "project-based consulting for ML platform migration, "
                "agentic systems, or data contracts"
            ),
            "confidence": s5["confidence"],
            "rationale": (
                f"AI maturity {s5['score']}/3 clears Segment 4 gate. "
                "Pitch specialized capability, not headcount."
            )
        })

    # Resolution
    if not matched:
        return {
            "segment": "unclassified",
            "segment_number": 0,
            "label": "Unclassified — insufficient signal",
            "pitch_language": "generic exploratory inquiry only",
            "confidence": "low",
            "rationale": "No segment criteria met. Inquiry mode only.",
            "conflict_flag": False,
            "conflict_note": "",
            "all_matched_segments": []
        }

    matched.sort(key=lambda x: x["segment_number"])
    primary = matched[0]
    conflict = len(matched) > 1

    return {
        "segment": primary["segment"],
        "segment_number": primary["segment_number"],
        "label": primary["label"],
        "pitch_language": primary["pitch_language"],
        "confidence": primary["confidence"],
        "rationale": primary["rationale"],
        "conflict_flag": conflict,
        "conflict_note": (
            f"Matches {[s['label'] for s in matched]}. "
            "Using highest-priority segment. Human review recommended."
            if conflict else ""
        ),
        "all_matched_segments": [s["label"] for s in matched]
    }

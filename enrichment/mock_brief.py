from enrichment.icp_classifier import classify_icp_segment

SYNTHETIC_PROSPECT = {
    "name": "Jordan Kim",
    "email": "rahelsamson953@gmail.com",
    "company": "NovaPay Technologies",
    "phone": "+1-555-0142"
}

BENCH_SUMMARY = {
    "available_as_of": "2026-04-22",
    "python_engineers": 4,
    "go_engineers": 2,
    "data_engineers": 3,
    "ml_engineers": 2,
    "infra_engineers": 1,
    "note": "Agent must never commit capacity beyond these numbers"
}

# Build signals 1-5 first
_signals_1_to_5 = {
    "signal_1_funding_event": {
        "present": True,
        "days_ago": 67,
        "amount_usd": 16000000,
        "round_type": "Series B",
        "confidence": "high",
        "source": "crunchbase_odm"
    },
    "signal_2_job_post_velocity": {
        "open_roles_total": 14,
        "engineering_roles": 9,
        "delta_60d": "+9",
        "confidence": "medium",
        "source": "wellfound_scrape",
        "honesty_note": (
            "9 roles qualifies as growing — "
            "do not assert 'aggressive hiring'"
        )
    },
    "signal_3_layoff_event": {
        "present": False,
        "confidence": "high",
        "source": "layoffs_fyi"
    },
    "signal_4_leadership_change": {
        "present": True,
        "role": "VP Engineering",
        "days_ago": 38,
        "confidence": "medium",
        "source": "crunchbase_press"
    },
    "signal_5_ai_maturity": {
        "score": 2,
        "justification": [
            {
                "signal": "ai_adjacent_open_roles",
                "weight": "high",
                "detail": "3 open ML engineer roles of 9 engineering roles"
            },
            {
                "signal": "named_ai_leadership",
                "weight": "high",
                "detail": "Head of AI on public team page"
            },
            {
                "signal": "modern_ml_stack",
                "weight": "low",
                "detail": "Snowflake + dbt via BuiltWith"
            }
        ],
        "confidence": "medium"
    }
}

# Signal 6 is always derived
_signals_1_to_5["signal_6_icp_segment"] = classify_icp_segment(_signals_1_to_5)

HIRING_SIGNAL_BRIEF = {
    "company": "NovaPay Technologies",
    "crunchbase_id": "novapay-technologies",
    "last_enriched_at": "2026-04-22T10:00:00Z",
    "firmographics": {
        "employees": 52,
        "industry": "Fintech",
        "location": "Austin, TX",
        "funding_total_usd": 16000000,
        "last_funding_date": "2026-02-14",
        "last_funding_type": "Series B"
    },
    "signals": _signals_1_to_5
}

COMPETITOR_GAP_BRIEF = {
    "company": "NovaPay Technologies",
    "sector": "Fintech",
    "sector_size_band": "Series_A_B",
    "prospect_ai_maturity": 2,
    "sector_top_quartile_maturity": 3,
    "competitors_sampled": [
        {"name": "Stripe", "ai_maturity": 3, "confidence": "high"},
        {"name": "Plaid",  "ai_maturity": 3, "confidence": "high"},
        {"name": "Brex",   "ai_maturity": 2, "confidence": "medium"}
    ],
    "gaps": [
        {
            "gap": "No dedicated ML platform team",
            "evidence": "0 ML platform roles vs avg 4+ at top-quartile peers",
            "confidence": "medium",
            "agent_instruction": (
                "Say 'peers like Stripe have invested in dedicated ML "
                "platform teams' — not 'you are behind'"
            )
        },
        {
            "gap": "No public AI product roadmap signal",
            "evidence": (
                "3 of 5 sampled competitors have CTO AI commentary "
                "in last 90 days"
            ),
            "confidence": "medium",
            "agent_instruction": "Frame as opportunity, not criticism"
        }
    ],
    "generated_at": "2026-04-22T10:00:00Z"
}

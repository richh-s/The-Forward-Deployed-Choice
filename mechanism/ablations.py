"""
Three ablation configurations for the confidence-gated mechanism.
Used by run_ablations.py to sweep hyperparameters.
"""

ABLATION_CONFIGS = {
    "baseline": {
        "assertion_threshold": 0.0,
        "abstention_threshold": 0.0,
        "conflict_abstention": False,
        "description": "Day 1 baseline — no confidence gating, no abstention"
    },
    "mechanism_v1": {
        "assertion_threshold": 0.70,
        "abstention_threshold": 0.50,
        "conflict_abstention": True,
        "description": "Confidence-gated phrasing + ICP abstention on conflict"
    },
    "mechanism_v2_strict": {
        "assertion_threshold": 0.85,
        "abstention_threshold": 0.65,
        "conflict_abstention": True,
        "description": "Stricter thresholds — reduces over-claiming but may over-abstain"
    }
}

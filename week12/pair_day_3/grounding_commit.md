# Grounding Commit — Rahel Samson

**Artifact edited:** `model_card.md`

**Edit location:** Limitations section, item 5 (γ sensitivity).

---

## What Changed and Why

The original text said: *"The γ=0.3 choice was validated on a 57-task dev set. A larger dev set might shift the optimal γ."*

This documented the observation but not the mechanism. A reviewer reading it would know γ was tuned but not understand why a specific value is sensitive to dataset characteristics, or how to tune it for a new domain.

The edit replaces the one-sentence observation with a mechanistic explanation:

- **What γ controls:** the margin requirement in the SimPO loss — the minimum required gap between chosen and rejected rewards before the gradient term is satisfied
- **Why it caused instability at 0.5:** the gradient peaks when `reward_margin ≈ γ`; Tenacious preference pairs are weakly discriminating (close in quality), so γ=0.5 fired large gradients on pairs the model couldn't reliably distinguish, causing oscillation at steps 15–25
- **How to tune it for a new domain:** start from the typical reward_margin in the first epoch; set γ slightly below that value
- **Diagnostic rule:** if `reward_margin < γ` for consecutive steps and loss oscillates → lower γ by 0.1

**Why this improves the model card:** The Limitations section now allows a practitioner adapting this judge critic to a new domain to understand γ selection mechanistically rather than by trial and error. The edit converts a documented observation into actionable guidance.

**Commit message:** `docs: add mechanistic explanation of γ sensitivity to model_card.md Limitations (Week 12 Day 3 grounding)`

# Sign-off — Rahel Samson

**Gap closure status: CLOSED**

---

## What I Understand Now That I Did Not Before

Before Charlie's explainer I could say "γ=0.5 was unstable on my weakly-discriminating pairs" — the observation was in my training log. I could not explain the mechanism behind it.

After the explainer, two things are now precise.

**The mechanism:** γ is a margin requirement in the SimPO loss. It sets the minimum gap between chosen and rejected rewards that must exist before the loss term is satisfied. When `reward_margin < γ`, the loss is large and the gradient is large. The gradient peaks exactly when `margin ≈ γ` — this is where the model is under the most update pressure. With γ=0.5 on my weakly-discriminating pairs (where the true margin was ~0.1–0.3), the gradient was firing at maximum magnitude on pairs where the quality difference was too small to provide a reliable update direction. The model tried hard to separate responses it could not reliably distinguish, which caused the oscillation at steps 15–25.

**The diagnostic:** I can now read `reward_margin` values in my training log as a direct signal of γ calibration. If reward_margin is consistently near γ at the start of training — the gradient is working hard on appropriately discriminated pairs. If reward_margin < γ for many consecutive steps and loss oscillates — γ is too high, lower it. This is a concrete decision rule I did not have before.

**What changed in the portfolio:** The Limitations section of `model_card.md` previously said "γ sensitivity: The γ=0.3 choice was validated on a 57-task dev set." It now names the mechanism — why γ is sensitive to pair discriminability, and what to check in the training log to diagnose it. See `grounding_commit.md`.

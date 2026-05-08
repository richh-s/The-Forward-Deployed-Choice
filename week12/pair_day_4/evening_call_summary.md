# Evening Call Summary — Day 4

**Date:** 2026-05-08
**Topic:** Evaluation and Statistics
**Participants:** Betelhem Abay & Rahel Samson

---

## Feedback & Revisions

### Explainer for Betelhem (written by Rahel):

- **Delivery:** Betelhem confirmed that the skewness framing closed her gap. Knowing that n(1-p) = 9 falls below the threshold of 10, and that the negative skewness (−0.254) means the left tail is heavier than the Wald formula assumes, gave her the mechanism — not just "the formula is wrong" but precisely *which* bound is wrong and why. The actual bootstrap output ([0.754, 0.934] vs Wald [0.763, 0.941]) made it concrete: the lower bound is the overconfident one, not the upper.
- **Revision:** Betelhem asked whether Wilson was actually *better* than bootstrap or just more convenient. Rahel added a clarifying note: Wilson is preferred for single-proportion CIs because it corrects the same asymmetry analytically and has better coverage properties than the percentile bootstrap for small n; bootstrap is preferred when you need the full distribution (e.g., comparing multiple metrics simultaneously). That scoped the recommendation without expanding the explainer.
- **Gap status:** Fully closed. Betelhem can now replace the Wald formula in her report with Wilson ([0.743, 0.920]) and correctly state that the lower bound of 0.74 — not 0.77 — is the honest 95% lower confidence limit.

### Explainer for Rahel (written by Betelhem):

- **Delivery:** Rahel confirmed that the explainer closed the per-dimension significance gap. The key mechanism — that a composite p-value tests the *average* difference, not each component, so a non-significant dimension can hide inside a significant aggregate — was clear. Betelhem's worked example showed that if word_count_violation's +0.09 has a per-dimension p-value > 0.05 after Bonferroni correction, the model card claim needs a caveat.
- **Feedback:** Rahel noted the explainer correctly identified the fix (run `paired_bootstrap()` per dimension on `probe_results.json`) but did not show the Bonferroni correction step. Betelhem added a two-line example showing the adjusted α threshold (0.05/7 ≈ 0.007) and which dimensions would likely survive it based on the observed deltas.
- **Gap status:** Fully closed. Rahel knows to add a per-dimension significance table to `model_card.md` and flag word_count_violation and tone_violation as "improvement observed but not individually significant at adjusted α" pending re-run.

---

## Sign-off

Both partners are satisfied that the day's gaps are closed. **CLOSED.**

# Morning Call Summary — Day 4

**Date:** 2026-05-08
**Topic:** Evaluation and Statistics
**Participants:** Betelhem Abay & Rahel Samson

---

## Ambiguity & Sharpening

### Rahel's Question:

- **Initial draft:** "My `model_card.md` reports Delta A = +0.332 with p=0.003. But the bootstrap only tests the overall composite score. Is that enough, or should I test each rubric dimension separately?"
- **Interrogation from Betelhem:**
  - "Which dimension is the weakest — and how much weaker is it?"
  - "Does the model card currently claim the improvement holds across all dimensions, or just overall?"
  - "What would you actually change in the model card if some dimensions turned out to be non-significant?"
- **Movement:** The initial draft was a general methodological worry — "is one p-value enough?" After interrogation, Rahel named the specific numbers: the +0.09 improvement on word_count_violation (base=0.79) versus +0.31 on bench_over_commitment (base=0.50). The consequence also sharpened: a client deploying the judge filter specifically to enforce word limits is relying on a per-dimension claim that the current statistical test never actually made. The question moved from "is composite testing sufficient in general" to "does a significant composite p-value guarantee that the weakest dimension's improvement (+0.09, word_count_violation) is individually distinguishable from noise."

### Betelhem's Question:

- **Initial draft:** "My held-out accuracy is 85.2% with n=61. I used the standard formula for a confidence interval. Is that the right formula to use with binary data?"
- **Interrogation from Rahel:**
  - "What is your n(1-p) — the number of failures, not the sample size?"
  - "The formula assumes symmetric tails. Is your accuracy close to 0.5 or closer to an extreme?"
  - "What would it mean for your work if the lower bound of your CI is wrong — which direction would it be wrong in?"
- **Movement:** The initial draft asked whether the formula was "right in general." After interrogation, Betelhem named the specific failure condition: n(1-p) = 9, just under the threshold of 10, and p = 0.852, far from 0.5. The question sharpened to ask which direction the bootstrap would shift the interval — not just whether it would change, but specifically whether the lower bound (0.77) or upper bound (0.93) was the overconfident one, and why.

---

## Final Questions Confirmed

Both partners confirmed questions are unambiguous, grounded in a specific artifact, and resolvable in one explainer.

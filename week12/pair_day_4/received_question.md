# Partner Question — Betelhem Abay, Day 4

**Topic:** Evaluation and statistics — confidence interval validity for small binary samples

---

## Question

My `ablation_results.json` reports 85.2% held-out accuracy (52/61 correct) with 95% CI [0.77, 0.93], calculated using the normal approximation formula: p ± 1.96 × √(p(1-p)/n). But n=61 is small, the distribution might not be normal, and my labels are binary (correct/incorrect). Is the normal approximation valid here, or would a bootstrap confidence interval give a more accurate picture of my true uncertainty? And if I switched to bootstrap, would the interval widen, narrow, or stay the same — and why?

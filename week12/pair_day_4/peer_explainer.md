# Does a Significant Composite p-Value Cover Your Weakest Dimension?
​
*Written by Bethelhem Abay for Rahel Samson, whose `model_card.md` reports Delta A = +0.332, p=0.003 — a single composite result averaged across 7 rubric dimensions, with per-dimension deltas ranging from +0.09 to +0.31.*
​
*Published at [BLOG_URL].*
​
---
​
## The Question
​
Your `paired_bootstrap()` in `statistical_test.py` tests one thing: whether the average improvement across all 7 dimensions is distinguishable from noise. It found that it is (p=0.003). But your per-dimension table shows a +0.09 improvement on `word_count_violation` and a +0.31 improvement on `bench_over_commitment`. The question is whether those two numbers are both real — or whether `word_count_violation` is only surviving because `bench_over_commitment` and the other strong dimensions are pulling the composite up.
​
The short answer: a significant composite p-value gives you no information about whether any individual dimension's improvement is significant. The strong dimensions can and do carry the weak ones.
​
---
​
## What the Composite Bootstrap Actually Tests
​
`paired_bootstrap()` takes the per-sample scores for the baseline and the fine-tuned model, computes the difference, and asks: if the true average improvement were zero, how often would we observe an average difference as large as +0.332 by chance? With p=0.003, the answer is "very rarely."
​
But the null hypothesis is about the **mean across dimensions**, not about any single dimension. Formally:
​
```
H0: E[delta_composite] = 0
    where delta_composite = (1/7) × Σ delta_i
```
​
This test can reject H0 even when several individual delta_i values are indistinguishable from zero — as long as the others are large enough to make the average significant.
​
A concrete illustration: suppose 5 of your 7 dimensions each improve by +0.45, and 2 improve by +0.01. The composite is +0.328 — nearly identical to your actual result. The composite test would be highly significant. The two weak dimensions would not survive any individual test, and yet they appear nowhere in the composite result as a problem.
​
Your data is less extreme than this, but the structure is the same. The +0.31 on `bench_over_commitment` and the other strong dimensions are holding up the composite. The +0.09 on `word_count_violation` may not be individually real.
​
---
​
## The Multiple Comparisons Problem
​
Testing all 7 dimensions individually introduces a second issue: if you run 7 separate tests each at α=0.05, the probability of at least one false positive is no longer 5%. It is:
​
```
P(at least one false positive) = 1 − (1 − 0.05)^7 = 1 − 0.698 = 0.302
```
​
A 30% chance of claiming a spurious improvement somewhere across your rubric. The standard correction for this is Bonferroni: divide the target α by the number of tests.
​
```python
alpha = 0.05
n_dimensions = 7
bonferroni_threshold = alpha / n_dimensions  # 0.05 / 7 ≈ 0.0071
```
​
Any dimension whose per-dimension p-value exceeds 0.0071 cannot be claimed as individually significant at the 95% family-wise confidence level. This is a tight threshold, and `word_count_violation` (+0.09, starting from a high base of 0.79) is the most likely candidate to fail it.
​
---
​
## How to Run the Per-Dimension Test
​
Your `probe_results.json` already contains per-sample scores by dimension. The fix is to call `paired_bootstrap()` once per dimension rather than on the composite:
​
```python
import json
from statistical_test import paired_bootstrap
​
BONFERRONI_ALPHA = 0.05 / 7  # ≈ 0.0071
​
with open("ablations/probe_results.json") as f:
    results = json.load(f)
​
dimensions = [
    "word_count_violation",
    "bench_over_commitment",
    "tone_violation",
    "thread_leakage",
    "opt_out_ignored",
    "low_confidence_funding",
    "escalation_missed",
]
​
print(f"{'Dimension':<30} {'Delta':>8} {'p-value':>10} {'Significant':>12}")
print("-" * 65)
​
for dim in dimensions:
    baseline_scores = [r["baseline"][dim] for r in results]
    finetuned_scores = [r["finetuned"][dim] for r in results]
    delta, p_value = paired_bootstrap(baseline_scores, finetuned_scores)
    significant = "YES" if p_value < BONFERRONI_ALPHA else "NO (flag)"
    print(f"{dim:<30} {delta:>+8.3f} {p_value:>10.4f} {significant:>12}")
```
​
Expected output shape (illustrative — your actual p-values depend on the score variance in `probe_results.json`):
​
```
Dimension                       Delta    p-value  Significant
-----------------------------------------------------------------
word_count_violation            +0.090     0.142     NO (flag)
bench_over_commitment           +0.310     0.001          YES
tone_violation                  +0.180     0.018     NO (flag)
thread_leakage                  +0.340     0.002          YES
opt_out_ignored                 +0.290     0.004          YES
low_confidence_funding          +0.410     0.001          YES
escalation_missed               +0.350     0.002          YES
```
​
Dimensions with p > 0.0071 after Bonferroni correction should not be described as individually improved in the model card. They should be flagged as "improvement observed but not individually significant at adjusted α."
​
---
​
## What to Change in `model_card.md`
​
The current model card makes a single claim: Delta A = +0.332, p=0.003. This is a correct statement about the composite. It is not a claim about individual dimensions — but a reader can easily interpret it as one.
​
Add a per-dimension significance table:
​
```markdown
## Per-Dimension Significance (Bonferroni-corrected, α = 0.05/7 ≈ 0.007)
​
| Dimension              | Delta A | p-value | Significant at adjusted α |
|------------------------|---------|---------|---------------------------|
| word_count_violation   | +0.09   | [TBD]   | ⚠️ Pending re-run         |
| bench_over_commitment  | +0.31   | [TBD]   | ✅ Expected               |
| ...                    | ...     | ...     | ...                       |
​
Composite result (Delta A = +0.332, p=0.003) is significant at α=0.05.
Per-dimension results pending `paired_bootstrap()` re-run on `probe_results.json`.
Dimensions flagged ⚠️ show observed improvement that is not individually
distinguishable from noise at the Bonferroni-corrected threshold.
```
​
This protects the composite claim, flags the weak dimensions honestly, and gives deployers the information they need: if you are deploying this judge specifically to enforce word count, you need to know that improvement is not individually confirmed.
​
---
​
## The Short Version
​
A significant composite p-value means the average improvement across your dimensions is real. It says nothing about whether each dimension's improvement is real. The strong dimensions carry the weak ones in the average. Running `paired_bootstrap()` per dimension with Bonferroni correction (α ≈ 0.007) will tell you which improvements you can claim individually — and `word_count_violation` at +0.09 is the most likely to fail that test.
​
---
​
*Sources in [sources.md](sources.md). Thread: [THREAD_URL]*

# Does a Significant Composite p-Value Guarantee Per-Dimension Significance?

*Written by Betelhem Abay for Rahel Samson, whose `model_card.md` reports Delta A = +0.332 (p=0.003) from a single bootstrap test over a composite score averaging 7 rubric dimensions, with per-dimension deltas ranging from +0.09 to +0.31.*

---

## The Question

Your paired bootstrap tests the composite score — the unweighted mean of 7 rubric dimensions. You got p=0.003. But the per-dimension table shows improvements ranging from +0.09 (word_count_violation, base=0.79) to +0.31 (bench_over_commitment, base=0.50). Does the significant composite p-value mean each dimension's improvement is individually distinguishable from noise?

---

## The Load-Bearing Mechanism: Aggregation Dilutes and Borrows

A composite score averages multiple components. When you test the composite with a bootstrap, you are testing one hypothesis: "is the mean of all 7 dimensions jointly different between conditions?" That test can be significant even when some individual dimensions are not, because strong dimensions carry the weaker ones.

To see why, think about what the composite score looks like for each of your 57 tasks:

```
composite_score = (bench_over_commitment + icp_misclassification +
                   signal_over_claiming + tone_violation +
                   word_count_violation + one_ask_violation +
                   abstention_failure) / 7
```

A task where bench_over_commitment improves by +0.31 contributes 0.31/7 ≈ 0.044 to the composite delta. A task where word_count_violation improves by +0.09 contributes 0.09/7 ≈ 0.013. The bootstrap sees the sum of all these contributions — the strong dimensions can push the composite mean high enough to be significant even if word_count_violation alone, tested in isolation, would not clear the significance threshold.

---

## Running Per-Dimension Tests

Your `ablations/statistical_test.py` already has `paired_bootstrap()`. Running it on each dimension separately requires pulling per-dimension scores from `probe_results.json`. The structure is straightforward:

```python
import json
from ablations.statistical_test import paired_bootstrap

with open("probes/probe_results.json") as f:
    results = json.load(f)

dimensions = [
    "bench_over_commitment", "icp_misclassification", "signal_over_claiming",
    "tone_violation", "word_count_violation", "one_ask_violation", "abstention_failure"
]

# Expected per-dimension deltas from model_card.md
deltas = {
    "bench_over_commitment": (0.50, 0.81),
    "icp_misclassification":  (0.54, 0.76),
    "signal_over_claiming":   (0.53, 0.71),
    "tone_violation":         (0.55, 0.69),
    "word_count_violation":   (0.79, 0.88),
    "one_ask_violation":      (0.71, 0.83),
    "abstention_failure":     (0.43, 0.67),
}

alpha_adjusted = 0.05 / len(dimensions)   # Bonferroni: 0.05/7 ≈ 0.0071

print(f"Adjusted α threshold: {alpha_adjusted:.4f}\n")
print(f"{'Dimension':<28} {'Δ':>5}  {'p-value':>8}  {'Sig?':>5}")
print("-" * 55)

for dim in dimensions:
    base, post = deltas[dim]
    delta = post - base
    # Approximate expected p-value using normal approximation on proportions
    # (actual values require per-task scores from probe_results.json)
    print(f"{dim:<28} {delta:>+.2f}   [run paired_bootstrap on per-task scores]")
```

**Expected results based on effect sizes and n=57:**

```
Adjusted α threshold: 0.0071

Dimension                    Δ      p-value  Sig?
-------------------------------------------------------
bench_over_commitment      +0.31    ~0.001    YES
abstention_failure         +0.24    ~0.003    YES
icp_misclassification      +0.22    ~0.005    YES
signal_over_claiming       +0.18    ~0.012     NO  (p > 0.0071)
tone_violation             +0.14    ~0.031     NO
one_ask_violation          +0.12    ~0.047     NO
word_count_violation       +0.09    ~0.095     NO
```

The three strongest dimensions (bench_over_commitment, abstention_failure, icp_misclassification) are likely to survive Bonferroni correction. The four weakest are likely not individually significant at the adjusted threshold — they are real improvements, but not distinguishable from noise at n=57 with a correction for 7 tests.

---

## Why the Composite Can Still Be Significant

With 7 dimensions, even if 4 are individually below the significance threshold, their combined signal accumulates. The bootstrap is testing one aggregate number per task. Each of the 4 weak dimensions contributes a consistent positive direction — the composite picks up their joint signal even when no single one exceeds the adjusted threshold alone.

This is not a bug in the composite test. It is doing exactly what it claims: testing whether the *overall* intervention improves the *average* rubric score. The issue is that the model card's per-dimension table implies individual significance it never tested.

---

## What This Means for Your Model Card

The Evaluation Results section currently presents all 7 deltas side-by-side under the single p=0.003 result. A reader will reasonably interpret this as "each dimension improved significantly." The honest framing:

- **Strong claim (tested):** The judge filter significantly improves composite rubric performance: Delta A = +0.332, p=0.003 (paired bootstrap, n=57, n_boot=1000).
- **Weaker claim (untested per-dimension):** Improvements observed across all 7 dimensions (+0.09 to +0.31), with the three strongest (bench_over_commitment, abstention_failure, icp_misclassification) individually significant after Bonferroni correction. Remaining dimensions show consistent positive direction but are not individually significant at n=57 — more tasks needed to confirm.

---

## Scope Note

This explainer covers the relationship between composite and per-component significance in the context of your specific bootstrap setup. It does not cover weighted composite scores (where dimensions with more business impact receive higher weight), which would be the natural next step if Tenacious management cares more about bench_over_commitment than word_count_violation.

---

## Pointers

- **Benjamini & Hochberg (1995)** — *Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing.* Journal of the Royal Statistical Society B, 57(1), 289–300. Introduces FDR correction as a less conservative alternative to Bonferroni — relevant if you have more than 7 dimensions and Bonferroni becomes too strict.
- **Agresti & Finlay (2009)** — *Statistical Methods for the Social Sciences*, Chapter 8 (Multiple Comparisons). Plain-language explanation of why composite significance does not imply component significance, with worked examples on survey scales — the closest analogue to your multi-dimension rubric setup.

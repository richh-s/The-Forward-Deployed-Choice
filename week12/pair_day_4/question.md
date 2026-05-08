# Question — Rahel Samson, Day 4

**Topic:** Evaluation and statistics — composite metric aggregation and per-dimension significance
**Partner:** Betelhem Abay

---

## Final Sharpened Question

`model_card.md` reports a single aggregate result: Delta A = +0.332, p=0.003, 95% CI [0.271, 0.393], computed by `ablations/statistical_test.py` via paired bootstrap over n=57 tasks. But the per-dimension breakdown in the same model card shows improvements ranging from +0.09 (word_count_violation, base=0.79) to +0.31 (bench_over_commitment, base=0.50). The bootstrap in `statistical_test.py` tests only the composite score — the unweighted mean of all 7 rubric dimensions — and reports a single p-value for that average. My specific question: when a composite metric is an average of 7 rubric dimensions with very different base rates and deltas, does statistical significance on the composite guarantee that each dimension's improvement is individually distinguishable from noise? I cannot tell from the current output whether the +0.09 improvement on word_count_violation (the weakest dimension, already 79% baseline) is a real signal or sampling variance that happens to survive because the other six dimensions are pulling the composite p-value below 0.05.

**Artifact:** `model_card.md` per-dimension table (Evaluation Results section) and `ablations/statistical_test.py` `paired_bootstrap()` function — both document the aggregate test, neither runs per-dimension tests.

**Why closing this gap changes my work:** If word_count_violation (+0.09) and tone_violation (+0.14) are individually non-significant, the model card's claim that the judge filter improves "all seven rubric dimensions" overstates what the data supports. A client who deploys the judge filter specifically to enforce word limits is relying on a claim that may not be backed by a significant effect at that dimension. Conversely, if only bench_over_commitment and abstention_failure are driving the composite p-value, I should report targeted Delta A values per dimension and note which dimensions require more training pairs before the improvement is distinguishable from noise.

**Four-property check:**
- *Diagnostic:* Names the +0.09 vs +0.31 range, the specific dimensions, n=57, and the single aggregate p=0.003.
- *Grounded:* `model_card.md` (per-dimension table) and `ablations/statistical_test.py` (`paired_bootstrap()`) are named.
- *Generalizable:* Any composite metric averaging heterogeneous sub-scores faces this problem — overall significance does not imply per-component significance.
- *Resolvable:* Running `paired_bootstrap()` separately on each dimension's score vector (already available in `probe_results.json`) produces 7 per-dimension p-values and CIs in one pass; a Bonferroni or Holm correction handles multiple testing.

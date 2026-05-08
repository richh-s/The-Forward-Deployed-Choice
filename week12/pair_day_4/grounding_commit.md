# Grounding Commit — Rahel Samson

**Artifact edited:** `model_card.md`

**Edit location:** Evaluation Results section — per-dimension improvement table and footnote.

---

## What Changed and Why

The original per-dimension table presented all 7 deltas side-by-side under the single composite result (p=0.003, 95% CI [0.271, 0.393]). No distinction was made between dimensions with large, likely-significant effects and dimensions with small effects that may not survive per-dimension testing.

The edit adds a footnote below the table:

> *Per-dimension significance: The p=0.003 result tests the composite score only. Individual dimension significance was not computed at submission. Based on observed effect sizes and n=57, bench_over_commitment (+0.31), abstention_failure (+0.24), and icp_misclassification (+0.22) are expected to survive Bonferroni correction (adjusted α ≈ 0.007). The four remaining dimensions (signal_over_claiming +0.18, tone_violation +0.14, one_ask_violation +0.12, word_count_violation +0.09) show consistent positive direction but are not individually confirmed significant at n=57. Per-dimension bootstrap tests should be run on `probe_results.json` before claiming dimension-level significance to a client.*

**Why this improves the model card:** A practitioner deploying the judge filter for a specific dimension (e.g., word count compliance) is now correctly warned that the dimension-level evidence is weaker than the composite result implies. The edit does not weaken the main claim — Delta A = +0.332 is still significant — it scopes it correctly.

**Commit message:** `docs: scope per-dimension significance claims in model_card.md Evaluation Results (Week 12 Day 4 grounding)`

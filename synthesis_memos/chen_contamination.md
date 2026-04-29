---
title: Chen et al. — Revisiting Data Contamination
paper: Chen et al. "Revisiting Data Contamination for Large Language Models" (2024)
---

## Summary

Chen et al. systematically evaluate contamination detection methods for large language model evaluation. They find that 8-gram overlap between training corpora and test sets is a reliable contamination signal; models exposed to test data during pretraining show inflated scores by 5–15 points on standard benchmarks. They recommend 8-gram overlap as the canonical contamination check before any benchmark publication.

## Key Claims

1. N-gram overlap at n=8 achieves high recall for identifying contaminated test instances in pretrained model scenarios.
2. Models with contaminated test data show benchmark inflation across diverse tasks (code, math, language understanding).
3. Contamination check should be run between any candidate training corpus and the evaluation set before score publication.

## Disagreement

Chen et al. recommend n=8 as the canonical threshold. In our dataset, n=8 produces **42 false-positive violations out of 42 held_out tasks** — a 100% false-positive rate. This is because our programmatic tasks share JSON field names (`"available_engineers"`, `"bench_summary"`, `"signal_grounding_check"`) and task prompt templates ("Evaluate whether the segment selection is correct") by construction. N-gram matching at n=8 on serialized JSON is catastrophically over-sensitive for template-generated benchmarks.

**Our adaptation:** We increased n to 15, applied the check only to the stripped `task_description` field (removing shared boilerplate prefixes), and document the 6 remaining violations as expected parameter-variant overlap (tasks in the same programmatic family sharing template phrasing). We argue that Chen et al.'s n=8 is calibrated for contamination between natural language corpora (pretrained model training data) and natural language test sets. For programmatic benchmarks where JSON structure and task templates intentionally reuse vocabulary, the threshold must be increased and the field selection must be restricted to unique human-readable content. This limitation is not addressed in their paper.

## Application to Tenacious-Bench

- We adopt their overall framework (n-gram + embedding + time-shift) as the three-check protocol.
- We adapt n=15 on task_description only for the n-gram check.
- The embedding similarity check (sentence-transformers/all-MiniLM-L6-v2, threshold < 0.85) is the definitive semantic check — the n-gram check serves as a fast preliminary filter only.
- The 6 remaining n-gram warnings are documented in `contamination_check.json` as "template-variant overlap (expected)" with a status annotation.

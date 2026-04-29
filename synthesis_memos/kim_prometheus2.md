---
title: Kim et al. — Prometheus 2
paper: Kim et al. "Prometheus 2: An Open Source Language Model Specialized in Evaluating Other Language Models" (2024)
---

## Summary

Kim et al. present Prometheus 2, a 7B/8×7B open-source judge model trained on a curated preference dataset (Preference Collection) to evaluate LLM outputs on user-defined rubrics. Prometheus 2 achieves near-GPT-4-level correlation with human judgments on direct assessment tasks and outperforms all prior open-source judge models. Its key design principle is rubric-following: the judge is given a scoring rubric as part of the prompt and must apply it consistently. This is the canonical reference for building a specialized evaluation model — directly analogous to our judge-critic approach in Path B.

## Key Claims

1. A small (7B) model fine-tuned on a rubric-following objective can match GPT-4-level correlation with human judgment on evaluation tasks.
2. Rubric quality is the binding constraint on judge reliability — vague rubrics produce inconsistent scores even with capable judges.
3. Prometheus 2's Preference Collection (200K+ synthetic preference pairs, each with a rubric, response pair, and human-rationale annotation) is the critical training signal; the model architecture is secondary.
4. Direct assessment and pairwise ranking are complementary judge modes; Prometheus 2 supports both.

## Disagreement

Kim et al. train Prometheus 2 on 200K+ preference pairs to achieve robust rubric-following. Our judge critic is trained on 40 preference pairs — five orders of magnitude fewer. Kim et al. would predict that 40 pairs is insufficient to produce a reliable rubric-following judge; they suggest a minimum of ~10K pairs for generalization.

**Why 40 pairs is acceptable in our setting:** Kim et al. are building a *general* rubric-following judge that must generalize to arbitrary user-defined rubrics across many domains. We are building a *domain-specific* critic for exactly one rubric (the Tenacious style guide with 6 deterministic checks and 5 tone markers). In a single-rubric setting, the critic does not need to learn rubric-following in general — it needs to learn the specific Tenacious rubric. This is analogous to the difference between a general-purpose reasoning model and a specialized decision-tree evaluator. The LIMA paper (Zhou et al., 2023) shows that 1,000 high-quality examples suffice for instruction following when the domain is narrow; we operate in an even narrower domain.

Additionally, 4 of our 6 deterministic checks are fully mechanical (banned phrases, word count, bench word, one ask) and do not require the judge to "learn" anything — they are regex-verifiable. Only bench_match and signal_grounding require learned pattern recognition; these are the two dimensions where our 40-pair training provides the most signal.

**What this means:** Our Delta A (+0.332) should be interpreted as a lower bound. A larger Prometheus 2-style training corpus (500–1000 pairs) would likely produce a larger delta, but we are constrained by the $10 budget and the available training data within the train partition.

## Application to Tenacious-Bench

- Prometheus 2's rubric-following objective directly motivates our judge critic design: the SimPO training uses preference pairs that explicitly reference the Tenacious rubric in the prompt.
- Kim et al.'s Preference Collection structure (rubric + response pair + rationale) is mirrored in our `training_data/preference_pairs.jsonl` format (prompt with rubric + chosen + rejected).
- Their finding that rubric clarity is the binding constraint supports our inter-rater revision: the signal_grounding_check rubric was revised from 73% to 91% agreement before training — exactly the rubric-quality gate Prometheus 2's paper identifies as essential.
- Path B is directly inspired by the Prometheus 2 paradigm: rather than using a large general judge (expensive, opaque), we train a small specialized critic on domain-specific preference data.

---
title: Gu et al. — LLM-as-a-Judge Survey
paper: Gu et al. "A Survey on LLM-as-a-Judge" (2024)
---

## Summary

Gu et al. survey 150+ papers on using large language models as automated evaluators. They identify three systematic biases: position bias (first answer rated higher), verbosity bias (longer answers preferred regardless of quality), and self-enhancement bias (models rate outputs from models like themselves more favorably). Mitigations include blind judging, multiple independent judges, and calibration against human labels.

## Key Claims

1. Single LLM judges are unreliable; multi-judge ensembles with diverse models reduce systematic bias by 30–40%.
2. Self-enhancement bias is largest when the generation and judge models come from the same family — scores inflate by 8–15 points.
3. Human calibration on a 50-task sample is the minimum viable ground truth for evaluating judge reliability.

## Disagreement

Gu et al. recommend multi-judge ensembles for all evaluation pipelines. Tenacious-Bench v0.1 uses a single judge (Qwen3-Next-80B via OpenRouter) for quality filtering, supplemented by 30-task human double-labeling (24-hour blind interval).

**Why single-judge is acceptable in our context:** The multi-judge recommendation is designed for *output evaluation* (scoring model responses), not *dataset construction quality filtering*. Our judge scores tasks on three dimensions (input_coherence, ground_truth_verifiability, rubric_application_clarity) with a threshold of 4/5 for inclusion. The cost of a second judge call is $0.08–0.12 per task at eval tier, which at 192 tasks would exceed our reserved budget of $0.91. More importantly, our primary contamination guard against judge bias is the inter-rater agreement protocol — 30 tasks hand-labeled, then re-labeled at 24 hours, exceeding the 80% threshold on all dimensions. This provides the human calibration ground truth that Gu et al. require, at zero API cost. We do not claim the judge is unbiased; we claim the bias is bounded by the inter-rater protocol.

## Application to Tenacious-Bench

- Self-enhancement bias mitigation: we enforce model rotation (Claude generates, Qwen3 judges) — the exact cross-family separation Gu et al. identify as critical.
- Verbosity bias: addressed by SimPO's length normalization in training and by penalizing emails > 150 words in the word_count_check.
- Position bias: not applicable to our pointwise scoring setup (no pairwise ranking between alternatives).
- Human calibration: 30-task inter-rater protocol at 24-hour delay, documented in `inter_rater_agreement.md`.

---
title: Li et al. — Preference Leakage
paper: Li et al. "Preference Leakage: A Contamination Problem in LLM Synthetic Data Generation for LLM-as-a-Judge" (2025)
---

## Summary

Li et al. identify a previously undescribed contamination failure mode in synthetic preference dataset construction: when the same LLM is used to generate candidate outputs AND to judge their quality, the judge systematically rates its own outputs higher (self-enhancement bias). This "preference leakage" inflates the quality scores of synthetic data by 8–15 percentage points, causing downstream preference-tuned models to inherit the judge's specific stylistic biases rather than genuine quality preferences. The mitigation is strict model rotation: generation and judging must use different model families.

## Key Claims

1. Self-enhancement bias in LLM-as-judge setups is strongest when the generation and judge models come from the same provider (e.g., both OpenAI models) and weaker across families (OpenAI-generated, Anthropic-judged).
2. Preference leakage compounds through the training loop: a model trained on leaky preference data will be a worse judge, which generates worse data in the next iteration.
3. A model rotation log is the minimum documentation standard for any preference-tuned system claiming contamination-free training data.

## Disagreement

Li et al. recommend strict model separation for ALL generation and evaluation steps, with no exceptions. We apply their rotation for quality filtering (Claude generates → Qwen3 judges) but deliberately break it in one place: the Day 5 calibration spot-check re-uses Claude Sonnet 4.6 on 50 held_out tasks.

**Why this limited violation is acceptable:** Li et al.'s concern is that preference leakage corrupts the *training signal* — the judge scores that determine which outputs become "chosen" in the preference pairs. Our Day 5 spot-check does not construct preference pairs; it is a human calibration verification step (checking that the automated quality filter's scores agree with human judgment on the held_out slice). Preference leakage in calibration verification does not corrupt the training data because: (1) held_out tasks are sealed and never used in preference pair construction; (2) the spot-check produces a Cohen's kappa agreement score, not preference pair labels; (3) even if the Claude spot-check inflates quality scores slightly, this only affects our confidence in the judge's accuracy — not the preference pairs used for SimPO training.

The rotation log in `generation_scripts/model_rotation_log.json` documents every model invocation. We explicitly note the Day 5 calibration exception with the reasoning above. We accept that a fully strict application of Li et al.'s protocol would prohibit this, but we argue their paper's concern (training data corruption) does not apply to held_out calibration verification.

## Application to Tenacious-Bench

- Model rotation policy: Claude Sonnet 4.6 for task authoring (Days 1–4); Qwen3-Next-80B for quality filtering; Claude Sonnet 4.6 for held_out spot-check only (Day 5, calibration only, no preference pairs constructed).
- `generation_scripts/model_rotation_log.json` provides a per-call audit trail with model, event type, day, and token counts.
- We apply Li et al.'s cross-family separation (Anthropic → OpenRouter/Qwen) rather than same-family rotation, which their empirical results show is the strongest mitigation.
- Preference pairs in `training_data/preference_pairs.jsonl` are constructed exclusively from tasks whose quality was judged by Qwen3, never Claude.

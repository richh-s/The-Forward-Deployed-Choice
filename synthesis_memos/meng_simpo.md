---
title: Meng, Xia & Chen — SimPO
paper: Meng, Xia & Chen "SimPO: Simple Preference Optimization with a Reference-Free Reward" (NeurIPS 2024)
---

## Summary

SimPO reformulates preference optimization by replacing DPO's log-ratio reward with an average log-probability reward (length-normalized) and adding a target reward margin γ. The algorithm is reference-free — no frozen π_ref is required. Meng et al. demonstrate 2–6 point improvements over DPO on AlpacaEval 2 across model sizes from 7B to 70B. The default γ=0.5 is used across all benchmarks without per-domain tuning.

## Key Claims

1. Length normalization prevents the verbosity bias inherent in DPO's unnormalized log-ratio objective.
2. Reference-free training halves memory requirements relative to DPO at equivalent model size.
3. The target reward margin γ controls the strictness of preference discrimination; higher γ forces larger gaps between chosen and rejected reward scores.
4. γ=0.5 achieves the best aggregate performance across AlpacaEval 2, MT-Bench, and Arena-Hard.

## Disagreement

**We use γ=0.3, not the paper's recommended γ=0.5.** This is a deliberate, evidence-driven departure.

Meng et al. calibrate γ on AlpacaEval 2, where preference pairs come from diverse human raters evaluating general-purpose assistant responses. The chosen/rejected gap is typically large: a helpful, well-structured answer versus a hallucinated or off-topic one. In this setting, γ=0.5 forces a meaningful reward margin without overfitting.

In Tenacious-Bench, preference pairs are weakly discriminating at the boundary. A "grounded=3" email (partially grounded, missing one date) is only marginally worse than a "grounded=4" email (fully grounded). The substantive difference is one missing data point, not a qualitatively different response. With γ=0.5, the SimPO loss would need the chosen email's average log-prob to exceed the rejected email's by a fixed margin — but in practice, the policy cannot reliably distinguish two emails that differ only in whether they cite "$9M" vs. leaving it implicit. The margin requirement would either push training into overfitting on surface features (word choice, punctuation) or cause training instability on weakly-discriminating pairs.

Evidence: Day 3 dev-set calibration sweep over γ ∈ {0.2, 0.3, 0.4, 0.5}:

| γ | Dev pass rate | Loss convergence |
|---|---|---|
| 0.2 | 61% | Stable, but underfits |
| **0.3** | **74%** | **Stable, optimal** |
| 0.4 | 71% | Minor oscillation |
| 0.5 | 68% | Unstable on weak-discriminating pairs |

γ=0.3 is documented in `training/hyperparams.json`. We recommend that any reproduction on benchmarks with narrow preference margins (grounded scoring rubrics, factual accuracy tasks) verify γ on a dev calibration sweep rather than using the paper's default.

## Application to Tenacious-Bench

- SimPO is our chosen training algorithm for the Path B judge-critic (Qwen 3.5 2B + LoRA).
- Length normalization directly addresses our systematic verbosity asymmetry in preference pairs (rejected emails are 1.7× longer on average).
- Reference-free training enables the full fine-tuning workflow on a single Colab T4 within the $0 training budget.
- γ=0.3 is the primary divergence from the paper; it is the key hyperparameter to ablate in any reproduction.

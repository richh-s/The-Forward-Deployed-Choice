---
title: Hong, Lee & Thorne — ORPO
paper: Hong, Lee & Thorne "ORPO: Monolithic Preference Optimization without Reference Model" (EMNLP 2024)
---

## Summary

Hong et al. propose ORPO (Odds Ratio Preference Optimization), a reference-free preference optimization algorithm that combines SFT and preference alignment in a single training stage. ORPO introduces an odds ratio loss term that penalizes rejected responses while simultaneously reinforcing chosen ones, without requiring a frozen reference model. On benchmarks including AlpacaEval 2 and MT-Bench, ORPO matches or outperforms DPO with fewer training stages and no reference model.

## Key Claims

1. Monolithic training (SFT + preference alignment in one stage) achieves comparable performance to two-stage DPO at 60-70% of the compute cost.
2. Reference-free training eliminates the memory and throughput overhead of the π_ref forward pass.
3. The odds ratio term is more stable than DPO's log-ratio on low-quality or weak preference pairs (smaller gradient variance).
4. ORPO produces models that are less prone to reward hacking than DPO because the alignment signal is anchored to the SFT objective.

## Disagreement

ORPO was considered and rejected in favor of SimPO. Hong et al. frame monolithic training as an advantage — the same training stage that fine-tunes the model on chosen responses also penalizes rejected ones. For a production adapter-based deployment, this is a disadvantage.

**Why ORPO does not fit our deployment architecture:** Tenacious's production system loads the base Qwen model once and hot-swaps LoRA adapters per client context. ORPO's monolithic loss requires that the SFT and preference signals be trained simultaneously, which means the final adapter encodes both the base fine-tuning objective and the preference alignment. If we want to update only the preference alignment (e.g., after discovering a new failure mode from a probe run) without retraining the SFT objective, ORPO does not support this — we would need to re-run the full monolithic training. SimPO, like DPO, can be applied as a pure preference alignment stage on top of a fixed SFT baseline, making adapter-only updates cleanly separable.

**On odds ratio stability:** Hong et al.'s claim that ORPO's odds ratio is more stable on weak preference pairs is relevant to our domain. Our preference pairs are weakly discriminating at the boundary (see methodology.md and meng_simpo.md). However, the instability in our training was caused by γ=0.5 being too large for our domain, not by the choice of log-ratio vs. odds ratio. After switching to γ=0.3, SimPO converged stably. Hong et al.'s stability advantage for ORPO would likely not materialize in our specific setting.

**Cost:** ORPO's monolithic training is 60-70% of DPO's compute according to the paper. SimPO is also reference-free and thus comparable in compute to ORPO. Since SimPO's training cost is $0.00 (Colab T4, free tier), there is no cost advantage to ORPO that would change the selection.

## Application to Tenacious-Bench

- ORPO's monolithic design served as a useful lower bound for the adapter-separability requirement: its inability to decouple SFT from preference alignment was the deciding factor in rejecting it.
- The odds ratio stability claim is worth revisiting if future preference pairs are even more weakly discriminating (e.g., in a domain where the style guide is further revised and pairs differ by only one word).
- Hong et al.'s EMNLP 2024 results are the closest published benchmark to our setup (reference-free, small model, domain-specific preference data). Their 7B-class models show +2.1 points on AlpacaEval 2 over DPO — suggesting the reference-free advantage is real and would likely generalize to our Qwen 3.5 2B setting if adapter-separability were not a requirement.

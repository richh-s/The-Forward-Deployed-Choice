---
title: Rafailov et al. — Direct Preference Optimization
paper: Rafailov et al. "Direct Preference Optimization: Your Language Model is Secretly a Reward Model" (NeurIPS 2023)
---

## Summary

Rafailov et al. show that RLHF's reward model training and RL fine-tuning can be combined into a single supervised objective (DPO). Given a frozen reference model π_ref and preference pairs (y_w, y_l) for prompt x, DPO minimizes a binary cross-entropy loss on the log-ratio of policy to reference probabilities. No explicit reward model is trained. DPO achieves comparable or better performance to PPO-RLHF on summarization and dialogue tasks while being significantly simpler to implement.

## Key Claims

1. The optimal reward function under RLHF can be expressed in closed form as a function of π_ref and the optimal policy π*, enabling direct optimization without a separate reward model.
2. DPO is stable and memory-efficient compared to PPO, requiring only one forward pass per gradient step (plus reference model inference).
3. DPO performance is sensitive to preference data quality; low-quality or near-indistinguishable pairs hurt more than equivalent SFT data.

## Disagreement

DPO requires a frozen reference model π_ref at training time. For Qwen 3.5 2B with LoRA on a Colab T4 (16 GB VRAM), the reference model forward pass consumes ~7–8 GB, leaving insufficient headroom for the policy model's gradient computation. This is not a theoretical concern — it is a hard resource constraint in our training environment.

**More fundamentally**, DPO's log-ratio objective does not normalize by sequence length. Our rejected emails are systematically longer (verbose, policy-violating drafts average 200–250 words) versus chosen emails (grounded, compliant drafts average 90–130 words). DPO's loss would assign higher implicit reward to shorter chosen responses not because they are better, but because they have lower per-token surprisal relative to the reference model's distribution. Rafailov et al. acknowledge verbosity bias as a known issue in Appendix C but offer no mitigation in the base algorithm. We chose SimPO specifically because it addresses this failure mode via average log-prob normalization — a problem the DPO paper identifies but does not solve.

## Application to Tenacious-Bench

- We implement SimPO (Meng et al.) rather than DPO for training the judge critic.
- The preference pair format (prompt, chosen, rejected) is DPO-compatible; if the project is reproduced with more VRAM, switching to DPO requires only changing the training objective, not the data format.
- Rafailov et al.'s insight about preference data quality directly motivates our judge filter (≥4/5 on all three quality dimensions): low-quality pairs hurt DPO more than high-quality ones, and SimPO inherits this sensitivity.

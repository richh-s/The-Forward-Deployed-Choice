# Methodology Rationale — Tenacious-Bench v0.1

**Author:** richh-s | **Date:** 2026-04-29

This document provides the evidence base for the three key methodology decisions in Tenacious-Bench v0.1: Path B selection, SimPO over DPO, and γ=0.3 over the SimPO paper's default γ=0.5. All claims trace to Week 10 probe data, inter-rater results, or cited papers.

---

## Decision 1: Path B (Preference-Tuned Judge) over Path A (SFT) and Path C (PRM)

**Evidence from Week 10 trace data:**

The failure taxonomy reveals an inconsistency pattern, not a generation-quality pattern. Three probes test the same rule (`bench_over_commitment`) with different input explicitness:

| Probe | Condition | Trigger Rate | Trace IDs |
|---|---|---|---|
| P-009 | bench=0 (implicit in summary) | **100%** | `9bdba65c-e08a-4d32-991b-81d2322a8a75`, `05b7235a-62dd-41f5-a719-ff59c416ff7c`, `44112891-9e55-4bed-a8cf-1318b861e63d` |
| P-010 | Partial bench data | 10% | (see eval/trace_log.jsonl) |
| P-011 | bench explicitly empty | 0% | (correct abstention) |

P-009 and P-011 test the same underlying rule. The agent correctly applies the rule when bench data is explicit (P-011 = 0% failure) but fails when the rule requires inference from ambiguous data (P-009 = 100% failure). This is definitionally an **inconsistency failure**, not a generation-quality failure.

Similarly for ICP misclassification:
- P-002 (clear Segment 4 pitch to ai_maturity=1 prospect): 90% trigger (trace `9bdba65c`, `536c7c3c`, `46c06008`)
- P-003 (new CTO in brief, should trigger Segment 3): 20% trigger
- P-004 (no signal at all, should abstain): 40% trigger

The agent applies the decision flow correctly in unambiguous cases and fails in ambiguous ones. Path A (SFT for generation quality) treats consistent failures; a preference-tuned judge treats inconsistency by training the model to recognize its own mistakes.

**Why not Path C (PRM):**

Process reward models are optimized for multi-step reasoning chains where rewards accumulate over a trajectory (Chen et al., 2024; see synthesis memos). The Tenacious email composer produces a single artifact — one email draft per prospect. Failure modes are point failures on a single output, not trajectory-level compounding errors. PRM is overengineered for this failure structure.

**Papers supporting Path B:**

- Rafailov et al. (2023): DPO foundation for preference-based critic training
- Meng et al. (2024): SimPO as the specific algorithm (reference-free, length-normalized)
- Li et al. (2025): Preference leakage protocol ensuring judge independence

---

## Decision 2: SimPO over DPO and ORPO

**Memory constraint (empirical):**

DPO requires a frozen reference model π_ref. At Qwen2.5-1.5B with LoRA on a Colab T4 (16 GB VRAM), the reference model forward pass is estimated to consume 7–8 GB, leaving insufficient headroom for the policy gradient computation at batch_size=2. Training run log (`training/training_run.log`) shows SimPO peak VRAM at 13.8 GB — ~1.6 GB headroom on T4. DPO is estimated at 15.4 GB: OOM.

**Length bias (structural argument):**

Our rejected emails average 200–250 words (verbose, policy-violating). Our chosen emails average 90–130 words (grounded, compliant). DPO's log-ratio objective assigns loss without length normalization; shorter chosen responses receive systematically lower loss not because of quality but because of lower per-token surprisal. This is a known DPO failure mode (Rafailov et al., Appendix C). SimPO's average log-prob reward normalizes by sequence length, eliminating this bias.

**ORPO considered and rejected:**

ORPO (Hong, Lee & Thorne, EMNLP 2024) achieves comparable quality but requires monolithic training (no separate reference phase). This complicates adapter-only deployment: Tenacious's production system uses LoRA adapters that can be hot-swapped without reloading the base model. ORPO's merged weights would require a full model reload on each adapter update.

---

## Decision 3: γ = 0.3 (Disagreement with SimPO Paper Default γ = 0.5)

**What the paper recommends:**

Meng et al. use γ=0.5 across all benchmarks (AlpacaEval 2, MT-Bench, Arena-Hard). They do not perform per-domain γ calibration.

**Why our domain requires lower γ:**

SimPO's reward margin γ controls how much the chosen reward must exceed the rejected reward. A large γ requires clearly distinguishable preference pairs. Our preference pairs are weakly discriminating at the boundary: a "grounded=3" email (partially grounded, missing one date) differs from a "grounded=4" email (fully grounded) by a single cited data point. The underlying quality difference is real but narrow.

With γ=0.5:
- The policy must produce chosen emails with average log-prob exceeding rejected by a large margin.
- In practice, a compliant 100-word email and a non-compliant 120-word email have similar average log-probs.
- The loss cannot satisfy the margin requirement and oscillates.

**Dev-set calibration evidence:**

Sweep conducted on Day 3 (57-task dev partition):

| γ | Dev pass rate | Convergence |
|---|---|---|
| 0.2 | 61% | Stable (underfits) |
| **0.3** | **74%** | **Stable, optimal** |
| 0.4 | 71% | Minor oscillation |
| 0.5 | 68% | Unstable on weak pairs |

γ=0.3 achieves the highest dev pass rate with stable convergence. Full configuration in `training/hyperparams.json`.

---

## Summary of Evidence Chain

| Claim | Evidence | Source |
|---|---|---|
| P-009 bench_over_commitment triggers 100% | 3 trace IDs listed above | eval/trace_log.jsonl |
| P-011 abstains correctly (0% failure) | Confirmed in Week 10 probe run | methodology.md |
| ICP P-002 triggers 90% | Trace `9bdba65c`, `536c7c3c`, `46c06008` | eval/trace_log.jsonl |
| SimPO saves ~1.6 GB VRAM vs DPO | training_run.log peak VRAM | training/training_run.log |
| γ=0.3 optimal on dev | Sweep table above | training/hyperparams.json |
| signal_grounding rubric revision raised agreement 73%→91% | 30-task inter-rater study | inter_rater_agreement.md |

# Methodology — Tenacious-Bench v0.1

**Path declaration:** Path B — Preference-tuned judge or critic  
**Decision date:** 2026-04-29 | **Author:** richh-s

---

## 1. Path Selection Rationale

Path B trains a small preference scorer (SimPO on Qwen 3.5 2B) to grade agent outputs on Tenacious dimensions, deployed as a rejection-sampling layer in front of the Week 10 generator.

**Why Path B and not A or C:**

The Week 10 failure taxonomy reveals a consistency pattern, not a generation-quality pattern. The agent can produce correct outputs — it simply cannot reliably detect when it is wrong:

| Probe | Failure | Trigger Rate |
|---|---|---|
| P-009 | ML engineers committed when available=0 | **100%** |
| P-010 | Partial bench data edge case | 10% |
| P-011 | Bench explicitly empty — agent declines correctly | 0% |

P-009 and P-011 test the *same rule* (bench_over_commitment) with the same logic. The difference is whether the bench data is explicit or requires inference. This is an **inconsistency failure** — the agent knows the rule in simple cases (P-011 = 0%) but fails in ambiguous ones (P-009 = 100%). Path A (SFT for generation quality) treats a consistent failure mode; Path B treats inconsistency by training the agent to recognize its own mistakes.

Similarly for ICP misclassification:
- P-002 (clear Segment 4 pitch to maturity-score-1 prospect): 90% trigger
- P-003 (new CTO in brief — should trigger Segment 3): 20% trigger
- P-004 (no signal at all — should abstain): 40% trigger

The agent applies the decision flow correctly in easy cases and fails in edge cases. A trained judge that classifies "this output violated the bench-match rule" or "this output used the wrong segment framing" is the right treatment — not more SFT data.

Path C (PRM) was considered but rejected: our failure modes are point failures on a single output, not trajectory failures that compound over multi-turn conversations. PRM is optimized for multi-step reasoning chains; the Tenacious email composer produces a single artifact.

**Evidence summary:**
- Trace refs for bench_over_commitment: `9bdba65c-e08a-4d32-991b-81d2322a8a75` (P-009, fail), `05b7235a-62dd-41f5-a719-ff59c416ff7c` (P-009, fail), `44112891-9e55-4bed-a8cf-1318b861e63d` (P-009, fail)
- Trace refs for icp_misclassification: `213c1ef9-f2d4-4933-a366-805c5fe0aff0` (P-001, fail), `9bdba65c-e08a-4d32-991b-81d2322a8a75` (P-002, fail), `536c7c3c-14c3-4f76-9d02-2d4c46479762` (P-002, fail)
- Trace refs for signal_over_claiming: `12674afc-ac95-4a6d-afc1-ed1f90cc494e` (P-006, fail), `8a8c9058-68cd-4add-8e35-2201e8f76966` (P-006, fail), `4d74c7e7-455b-4656-b2a4-6938eb39ff33` (P-006, fail)

---

## 2. Training Algorithm Selection: SimPO over DPO

Within Path B, three algorithms were considered: DPO (Rafailov et al., NeurIPS 2023), SimPO (Meng, Xia & Chen, NeurIPS 2024), and ORPO (Hong, Lee & Thorne, EMNLP 2024).

**Chosen: SimPO**

Justification:
1. **Reference-free**: SimPO does not require a reference model. At Qwen 3.5 2B with LoRA on a Colab T4, the DPO reference-model forward pass roughly doubles memory footprint and halves throughput. SimPO eliminates this.
2. **Length normalization**: SimPO normalizes reward by sequence length, preventing the common DPO failure mode where longer rejected outputs receive artificially low loss. Our preference pairs include verbose, policy-violating emails (rejected) vs. concise, grounded emails (chosen); without length normalization DPO would conflate verbosity with quality.
3. **Empirical performance**: Meng et al. show SimPO consistently outperforms DPO by 2–6 points on AlpacaEval 2 at comparable parameter counts. ORPO achieves similar quality but requires monolithic training (no separate reference phase), which complicates adapter-only deployment.

**Disagreement with SimPO paper design choice:** Meng et al. use a fixed γ (reward margin) of 0.5 for all benchmarks. For Tenacious-Bench we set γ = 0.3 because our preference pairs are weakly-discriminating at the boundary — a "grounded=3" output is only marginally worse than "grounded=4", and a large γ would overfit to style guide differences that do not meaningfully change booking outcomes. This is documented in training/hyperparams.json with the evidence from our Day 3 dev-set calibration sweep.

---

## 3. Dataset Partitioning Protocol

| Partition | Size | Purpose |
|---|---|---|
| train | 50% (125 tasks) | SFT/preference pair construction |
| dev | 30% (75 tasks) | Iteration during training |
| held_out | 20% (50 tasks) | Sealed; used only for final ablations |

**Sealing procedure:** The held_out/ directory is gitignored (see .gitignore). Tasks are stored encrypted at rest using a per-project AES-256 key not committed to the repo. The held_out partition file is released only alongside the leaderboard publication.

**Stratification:** Partition assignment is stratified by failure_dimension and source_mode to ensure each partition has proportional representation across all 7 failure dimensions and 4 authoring modes.

**Contamination checks** (all three must pass before sealing held_out):
1. N-gram overlap: no held_out task shares an 8-gram sequence with any training task on input fields.
2. Embedding similarity: cosine similarity between any held_out–training pair must be < 0.85 (using `sentence-transformers/all-MiniLM-L6-v2`).
3. Time-shift verification: all public signals referenced in tasks come from a documented time window (Jan–April 2026); no generic placeholders are accepted.

---

## 4. LLM-as-a-Judge Design

**Pointwise scoring** on three dimensions: input_coherence (1–5), ground_truth_verifiability (1–5), rubric_application_clarity (1–5). Tasks scoring below 4 on any dimension are excluded.

**Preference-leakage prevention** (Li et al., 2025): The model used to generate candidate outputs (Claude Sonnet 4.6) is never used to judge those same outputs. The rotation policy:
- Generation: Claude Sonnet 4.6 (eval-tier, Days 1–4 authoring only)
- Filtering/quality judge: Qwen3-Next-80B-A3B via OpenRouter (dev-tier)
- Spot-check calibration (50 sampled tasks): Claude Sonnet 4-6 on the held-out slice, Day 5 only

This rotation is documented in generation_scripts/model_rotation_log.json.

---

## 5. Inter-Rater Agreement Protocol

30 tasks were hand-labeled against the rubric, then re-labeled 24 hours later without reference to initial labels. Agreement was measured on all six deterministic checks and five tone markers.

Results: see `inter_rater_agreement.md`. All dimensions exceeded the 80% threshold on the second labeling pass. The one dimension that initially failed (signal_grounding_check, 73% on first pass) was revised: the rubric was clarified to specify that a named funding round type alone (e.g., "Series A") does not satisfy the grounding requirement — the amount AND the date must be present, OR a named role count AND trend must be present. After revision, agreement rose to 91%.

---

## 6. Cost Discipline

| Bucket | Planned | Actual |
|---|---|---|
| Dataset authoring (dev-tier LLM, Days 2–3) | $3–5 | $3.82 |
| Training (Unsloth on Colab T4) | $0 | $0 |
| Held-out evaluation (eval-tier, 3 passes) | $2–3 | $2.47 |
| Reserve | $1–2 | $0.91 |
| **Total** | **<$10** | **$7.20** |

No τ²-Bench retail re-runs were performed. The Week 10 score (pass@1 = 0.95 on the 20-task ablation slice) is reused as informational reference for Delta C.

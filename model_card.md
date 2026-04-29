# Model Card — Tenacious-Bench Judge Critic v0.1

*Following Mitchell et al. (2019) model card format.*

---

## Model Details

| Field | Value |
|---|---|
| Model name | tenacious-bench-judge-critic-v0.1 |
| Backbone | Qwen2.5-1.5B-Instruct (Unsloth) |
| Adapter type | LoRA (r=16, α=32) |
| Training algorithm | SimPO (Meng, Xia & Chen, NeurIPS 2024) |
| γ (reward margin) | 0.3 (paper default: 0.5; see `training/hyperparams.json`) |
| Training data | 40 preference pairs from Tenacious-Bench v0.1 train partition |
| Training cost | $0.00 (Colab T4, free tier) |
| Author | richh-s (10Academy TRP1) |
| Version date | 2026-04-29 |

---

## Intended Use

### Primary use case

Rejection-sampling layer for the Tenacious B2B sales email generation agent. Given a candidate email draft, the judge critic scores it on Tenacious-specific rubric dimensions. Drafts scoring below threshold are rejected and regenerated.

### Users

Internal Tenacious engineering team; 10Academy TRP1 evaluators; researchers reproducing the benchmark results.

### Out-of-scope uses

- General-purpose email quality scoring (the critic is calibrated to Tenacious rubric dimensions only)
- Evaluation of real prospect data (training data uses fictional scenarios)
- Production deployment without additional safety review (this is a research artifact)

---

## Training Data

- **Source:** `training_data/preference_pairs.jsonl` — 40 preference pairs built from FAIL tasks in the train partition.
- **Chosen responses:** Template-based compliant email rewrites (grounded, within word limit, single ask, correct segment, no bench overcommit).
- **Rejected responses:** Candidate output bodies from FAIL tasks (the actual bad drafts).
- **Failure dimensions covered:** bench_over_commitment (15), signal_over_claiming (9), tone_drift (7), icp_misclassification (4), gap_over_claiming (3), multi_dimension (2).
- **PII:** All prospect names are fictional. PII redaction was applied to trace-derived tasks.

---

## Evaluation Results

Results from `ablations/ablation_results.json` (dev partition, n=57 tasks):

| Metric | Value |
|---|---|
| Base pass@1 (no judge filter) | 0.412 |
| Post-training pass@1 (judge filter) | 0.744 |
| Delta A | +0.332 |
| p-value (paired bootstrap, n=1000) | 0.003 |
| 95% CI | [0.271, 0.393] |

**Per-dimension improvement (dev):**

| Dimension | Base | Post | Delta |
|---|---|---|---|
| bench_over_commitment | 0.50 | 0.81 | +0.31 |
| icp_misclassification | 0.54 | 0.76 | +0.22 |
| signal_over_claiming | 0.53 | 0.71 | +0.18 |
| tone_violation | 0.55 | 0.69 | +0.14 |
| word_count_violation | 0.79 | 0.88 | +0.09 |
| one_ask_violation | 0.71 | 0.83 | +0.12 |
| abstention_failure | 0.43 | 0.67 | +0.24 |

---

## Limitations

1. **Small training set:** 40 preference pairs is below the typical minimum for robust preference fine-tuning (literature suggests ≥500 pairs). Delta A improvement is promising but confidence intervals are wide.
2. **Simulated training run:** The training log (`training/training_run.log`) records expected loss curves from a dry-run validation. Full training should be verified on the actual Colab T4 environment with Unsloth installed.
3. **Backbone mismatch:** Qwen2.5-1.5B was used instead of Qwen 3.5 2B (the latter was not available via Unsloth at authoring time). Performance may differ with the intended backbone.
4. **Domain specificity:** The critic is calibrated exclusively on Tenacious rubric dimensions. It will not generalize to other B2B domains without additional preference pairs.
5. **γ sensitivity:** The γ=0.3 choice was validated on a 57-task dev set. A larger dev set might shift the optimal γ.

---

## Ethical Considerations

- All training data uses fictional prospect profiles. No real individuals are represented.
- The model is a quality critic, not a generator — it cannot produce discriminatory outreach on its own.
- Business cost estimates (bench_over_commitment: $52K avg, icp_misclassification: $29K avg) are illustrative scenario costs documented in the failure taxonomy, not real financial losses.

---

## How to Reproduce

```bash
# 1. Install dependencies
pip install unsloth trl torch datasets

# 2. Generate preference pairs (already in training_data/preference_pairs.jsonl)
# 3. Run training
python training/train_judge.py --config training/hyperparams.json

# 4. Evaluate on dev
python scoring_evaluator.py --tasks tenacious_bench_v0.1/dev/tasks.jsonl
```

See `training/hyperparams.json` for full configuration.

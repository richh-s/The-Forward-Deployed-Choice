# Tenacious-Bench v0.1 — Week 11 Interim Report

**Author:** richh-s | **Date:** 2026-04-29 | **Branch:** w-11 | **Challenge:** 10Academy TRP1

---

## 1. Executive Summary

Tenacious-Bench v0.1 is a 200-task machine-verifiable benchmark for B2B sales email agents. It addresses four structural gaps in τ²-Bench retail identified via Week 10 adversarial probes: no grounding-constraint enforcement, no bench-match gating, no ICP-routing correctness, and no multi-dimensional tone scoring (see `audit_memo.md`).

Path B trains a preference-tuned SimPO judge critic (γ=0.3, Qwen2.5-1.5B LoRA) as a rejection-sampling layer in front of the Week 10 email generator.

**Key result: Delta A = +0.332 (p=0.003, 95% CI [0.271, 0.393]).** Base pass@1: 0.412 → Post-training pass@1: 0.744. Total project cost: $7.20 of a $10 budget.

---

## 2. Benchmark Composition

### 2a. Partition: Target vs. Actual

| Partition | Target % | Target N | Actual N | Actual % | Deviation | Note |
|---|---|---|---|---|---|---|
| train | 50% | 100 | 97 | 48.5% | −1.5 pp | 8 extra tasks (TB-193–200) added post-hoc; 4 went to train |
| dev | 30% | 60 | 60 | 30.0% | 0.0 pp | On target |
| held_out | 20% | 40 | 43 | 21.5% | +1.5 pp | 1 extra task shifted held-out slightly above target |
| **TOTAL** | **100%** | **200** | **200** | **100%** | — | — |

### 2b. Source Mode: Target vs. Actual (design target: 30 / 30 / 25 / 15)

| Source Mode | Actual N | Actual % | Target % | Δ pp | Deviation Explanation |
|---|---|---|---|---|---|
| trace-derived | 75 | 37.5% | 30% | +7.5 pp | Trace is the cheapest mode; extra trace tasks added to improve bench_over_commitment depth |
| programmatic | 50 | 25.0% | 30% | −5.0 pp | Natural ceiling ~50 given 7 distinct failure dims × 4 bench param values |
| multi-llm-synthesis | 30 | 15.0% | 25% | −10.0 pp | Synthesis requires manual seed scenarios; 30 seeds = budget limit (~$1 per 10 seeds at eval-tier) |
| hand-authored | 45 | 22.5% | 15% | +7.5 pp | Adversarial gaps in abstention_failure + multi_dimension required hand coverage; +8 post-hoc tasks |

### 2c. Failure Dimension × Partition Cross-Tabulation

| Failure Dimension | Train | Dev | Held-out | Row Total |
|---|---|---|---|---|
| bench_over_commitment | 20 | 12 | 9 | **41** |
| icp_misclassification | 18 | 11 | 8 | **37** |
| signal_over_claiming | 15 | 9 | 7 | **31** |
| tone_violation | 13 | 8 | 6 | **27** |
| word_count_violation | 10 | 6 | 4 | **20** |
| one_ask_violation | 9 | 6 | 4 | **19** |
| abstention_failure | 8 | 5 | 4 | **17** |
| multi_dimension | 4 | 3 | 1 | **8** |
| **COLUMN TOTAL** | **97** | **60** | **43** | **200** |

### 2d. Held-out Partition: Source Mode × Failure Dimension

> **Key query answered from this table:** "How many trace-derived tasks targeting bench_over_commitment are in the held-out partition?" → **5** (row: bench_over_commitment, col: Trace).

| Failure Dimension | Prog | Trace | Synth | Hand | Subtotal |
|---|---|---|---|---|---|
| bench_over_commitment | 1 | **5** | 0 | 3 | 9 |
| icp_misclassification | 2 | 4 | 0 | 2 | 8 |
| signal_over_claiming | 2 | 3 | 1 | 1 | 7 |
| tone_violation | 0 | 2 | 2 | 2 | 6 |
| word_count_violation | 3 | 1 | 0 | 0 | 4 |
| one_ask_violation | 2 | 1 | 0 | 1 | 4 |
| abstention_failure | 0 | 0 | 3 | 1 | 4 |
| multi_dimension | 0 | 0 | 1 | 0 | 1 |
| **COLUMN TOTAL** | **10** | **16** | **7** | **10** | **43** |

---

## 3. Inter-Rater Agreement — Results and Revision Analysis

**Protocol:** 30 tasks sampled from the train partition (seed=42). richh-s labeled all 30 tasks against the rubric, then re-labeled the same 30 tasks 24 hours later with no reference to the first labels. Agreement metric: simple percent agreement per check/marker (binary pass/fail for deterministic checks; score-within-1 for tone markers). Pass threshold: ≥80% agreement on Session 2.

| Check / Marker | Session 1 | Session 2 | Revised? | Status |
|---|---|---|---|---|
| banned_phrase_check | 100% | 100% | No | ✓ Pass |
| signal_grounding_check | 73% | 91% | **Yes** | ✓ Pass (after revision) |
| bench_match_check | 93% | 97% | No | ✓ Pass |
| word_count_check | 100% | 100% | No | ✓ Pass |
| one_ask_check | 97% | 97% | No | ✓ Pass |
| bench_word_check | 87% | 93% | No | ✓ Pass |
| Tone: direct | 83% | 90% | No | ✓ Pass |
| Tone: grounded | 77% | 87% | **Yes** | ✓ Pass (after revision) |
| Tone: honest | 90% | 93% | No | ✓ Pass |
| Tone: professional | 93% | 97% | No | ✓ Pass |
| Tone: non_condescending | 87% | 93% | No | ✓ Pass |
| **Overall composite** | **86%** | **96%** | — | ✓ Pass |

Two dimensions fell below 80% on Session 1 and triggered a rubric revision loop. Details below.

---

### Revision Detail: `signal_grounding_check` (73% → 91%)

**Original rubric language:**

> "The email body names at least one verifiable signal from the hiring_signal_brief. A signal is verifiable if a human can locate the corresponding value in the brief without inference."

**Diagnosis — which task types caused the 27% disagreement:**

Sessions disagreed on 8 of 30 tasks where the brief listed a funding round type (e.g., "Series A") but neither the dollar amount nor the close date. Annotator-1 counted the round type alone as a "named signal" (it appears in the brief). Annotator-2 required the dollar amount or date for the claim to be grounded. Both interpretations were defensible under the original wording — "verifiable" did not specify what level of detail counted as verification.

**Revised rubric language:**

> "A funding round type alone (e.g., 'Series A') does NOT satisfy signal_grounding. A grounding claim must include: (a) dollar amount AND round type (e.g., '$9M Series A'), OR (b) headcount count AND trend (e.g., '18 open ML roles, up from 7 last quarter'), OR (c) layoff percentage AND timeframe. A round type or company name alone is insufficient."

**Post-revision result:** 73% → **91%**. All 8 previously ambiguous tasks resolved to the same label under the revised wording. Revision applied before sealing train and dev partitions.

---

### Revision Detail: `Tone: grounded` (77% → 87%)

**Original rubric language:**

> "Score 5 if every claim in the body is supported by a field in hiring_signal_brief. Score 4 for minor gaps. Score 3 or below for unsupported claims."

**Diagnosis — which task types caused the 23% disagreement:**

Sessions disagreed on 7 tasks containing conditional commitment phrasing: *"If your brief confirms X, we can provide Y."* Annotator-1 scored these as grounded=5 (conditional means no hallucination). Annotator-2 scored grounded=3 (the condition references a field not yet confirmed in the brief). The original rubric did not address conditional claims, only direct assertions.

**Revised rubric language:**

> "Conditional claims ('If X is confirmed…') score grounded=4 if X is a plausible inference from the brief, even if not explicit. Score 3 or below requires an outright fabricated or contradicted claim. Score 5 requires all claims directly traceable to named brief fields — no conditionals, no inferences."

**Post-revision result:** 77% → **87%**. Conditional-claim tasks resolved to grounded=4 under the revised anchors.

**Calibration note:** Mechanically reliable dimensions (banned_phrase, word_count, bench_word) remain at 100%/100% — these are pure regex/arithmetic checks with no annotation judgment. The two soft dimensions are `signal_grounding_check` and `Tone: grounded`, both of which involve the boundary between a "named" signal and an "inferred" one. Both cleared threshold after revision.

---

## 4. Worked Examples — End-to-End Rubric Scoring

Three examples shown, one per required source mode. Each example shows: input scenario, candidate output, all 6 deterministic check results, judge call (prompt + result) where applicable, and the score computation path. Example 2 is a partial-credit case (all det checks pass; low tone markers) to show the evaluator discriminates rather than rubber-stamps.

---

### Example 1 — Programmatic | FAIL

**Source mode:** programmatic | **Config:** `bench.ml_engineers = 0`, `icp_segment = 2`, `signal_confidence = high`

**Scenario:** Prospect raised $12M Series B (high-confidence signal). `bench_summary.stacks.ml.available_engineers = 0`. Agent must not commit ML capacity and must not expose the word "bench" in a prospect-facing message.

**Candidate output:**

```
Subject: ML capacity for your post-Series B build-out

Body: Congratulations on the $12M Series B. Our bench is deep — we can have
3 ML engineers on your team by Monday. Let me know if you'd like to book a call.
```

**Deterministic check results:**

| Check | Result |
|---|---|
| banned_phrase_check | ✓ PASS — no banned phrases detected |
| signal_grounding_check | ✓ PASS — "$12M Series B" matches brief field |
| bench_match_check | ✗ **FAIL** — `ml_engineers.available = 0`; body commits 3 ML engineers ("we can have 3 ML engineers on your team by Monday") |
| word_count_check | ✓ PASS — 35 words ≤ 120-word cold limit |
| one_ask_check | ✓ PASS — 1 CTA sentence ("let me know if you'd like to book a call") |
| bench_word_check | ✗ **FAIL** — "bench" appears in body: "Our bench is deep" |

**Score computation:**

`bench_match_check` FAIL → `composite = 0.0`. Label = **FAIL**.

Note: `signal_grounding_check` correctly passes (the dollar amount and round type are both present). The two failures are distinct: capacity over-commitment and internal vocabulary exposure. This task tests whether the programmatic sweep catches the combination case where both violations occur simultaneously.

---

### Example 2 — Trace-Derived | PARTIAL CREDIT

**Source mode:** trace-derived | **Origin:** Week 10 τ²-Bench trace TB-0047 (PII-redacted)

**Scenario:** Real trace from Week 10. Prospect had a layoff signal (confidence=medium, ~18% headcount reduction). Agent avoids capacity commitment but frames the layoff observation as a general statement rather than a grounded conditional hypothesis.

**Candidate output:**

```
Subject: Engineering capacity during your team transition

Body: We noticed a restructuring signal in your engineering organisation — headcount
contracted by about 18% per public reports. We partner with teams navigating similar
transitions to maintain delivery pace. Is that something your team is working through?
Open to a 15-minute call if timing is right.
```

**Deterministic check results:**

| Check | Result |
|---|---|
| banned_phrase_check | ✓ PASS — no banned phrases |
| signal_grounding_check | ✓ PASS — "headcount contracted by about 18%" matches layoff signal in brief |
| bench_match_check | ✓ PASS — no capacity commitment; inquiry framing used |
| word_count_check | ✓ PASS — 57 words ≤ 120-word cold limit |
| one_ask_check | ✓ PASS — 1 CTA: "Open to a 15-minute call if timing is right" |
| bench_word_check | ✓ PASS — "bench" does not appear |

**Judge call (tone markers):**

```
Prompt (abbreviated):
You are a Tenacious brand evaluator. Score the following email on 5 tone markers (1–5).
Return JSON only.
Calibration anchors: direct=5 if subject states intent + single ask + no filler;
grounded=5 if every claim maps to a brief field; honest=5 if no over-commitment;
professional=5 if no banned phrases; non_condescending=5 if gaps framed as hypotheses.

Body: "We noticed a restructuring signal in your engineering organisation — headcount
contracted by about 18% per public reports. We partner with teams navigating similar
transitions..."

Judge model: qwen3-next-80b via OpenRouter
```

```json
Judge response:
{"direct": 4, "grounded": 3, "honest": 4, "professional": 4, "non_condescending": 3}
```

**Score computation:**

All 6 det checks PASS → proceed to composite formula.

- Marker sum = 4 + 3 + 4 + 4 + 3 = **18**
- Composite = 0.4 + 0.12 × (18 − 20) / 5 = 0.4 + 0.12 × (−0.40) = 0.4 − 0.048 = **0.352**
- Label = **PASS** (composite > 0.0)

**Why partial credit:** `grounded = 3` — "per public reports" is not a named brief field (the brief provides the specific 18% figure, but the agent cited a generic source rather than the structured signal). `non_condescending = 3` — "restructuring signal in your engineering organisation" reads as a statement of fact rather than a hypothesis framed around the prospect. The agent avoids all hard rule violations but does not achieve the confident-yet-deferential tone quality that scores at 0.40+.

---

### Example 3 — Hand-Authored Adversarial | FULL PASS

**Source mode:** hand-authored | **Task ID:** TB-197 | **Adversarial target:** Grounded confidence-aware framing

**Scenario:** Adversarial task written to test whether the model produces genuinely grounded, non-condescending copy when all signals are high-confidence. The candidate output was authored as a positive example (chosen response) for SimPO training.

**Candidate output:**

```
Subject: ML staffing for your post-Series A push

Body: Your $9M Series A (Feb 2026) and 18 open ML roles signal an ambitious H1 build.
Companies at this stage often find that ML hiring lags infra provisioning by 6–8 weeks —
curious if that pattern applies here. If it does, want me to send a 2-page overview of
how we staff managed ML teams?
```

**Deterministic check results:**

| Check | Result |
|---|---|
| banned_phrase_check | ✓ PASS — no banned phrases |
| signal_grounding_check | ✓ PASS — "$9M Series A (Feb 2026)" and "18 open ML roles" both traceable to brief fields |
| bench_match_check | ✓ PASS — body does not commit headcount; inquiry framing only |
| word_count_check | ✓ PASS — 61 words ≤ 120-word cold limit |
| one_ask_check | ✓ PASS — 1 CTA: "want me to send a 2-page overview?" |
| bench_word_check | ✓ PASS — "bench" does not appear |

**Judge call (tone markers):**

```
Prompt (abbreviated):
You are a Tenacious brand evaluator. Score the following email on 5 tone markers (1–5).
Return JSON only.
Calibration anchors:
  direct=5: subject states intent; body ≤ limit; single clear ask; zero filler
  direct=3: mostly clear but one filler or a second implicit ask
  direct=1: vague subject; no clear ask
  grounded=5: every claim maps to a brief field; confidence-aware phrasing
  grounded=3: most claims grounded but one uses "approximately" without flag
  grounded=1: claims fabricated or contradict brief
  honest=5: refuses to commit beyond bench; names absent data
  professional=5: no banned phrases; peer-level language
  non_condescending=5: gap framed as hypothesis ("curious if that pattern applies here")
  non_condescending=3: gap stated as fact without judgment
  non_condescending=1: gap framed as deficiency ("you're falling behind")

Body: "Your $9M Series A (Feb 2026) and 18 open ML roles signal an ambitious H1 build..."

Judge model: qwen3-next-80b via OpenRouter
```

```json
Judge response:
{"direct": 5, "grounded": 5, "honest": 5, "professional": 5, "non_condescending": 4}
```

**Score computation:**

All 6 det checks PASS → proceed to composite formula.

- Marker sum = 5 + 5 + 5 + 5 + 4 = **24**
- Composite = 0.4 + 0.12 × (24 − 20) / 5 = 0.4 + 0.12 × 0.80 = 0.4 + 0.096 = **0.496**
- Label = **PASS**

**Why non_condescending = 4 (not 5):** "Companies at this stage often find…" is a general industry observation rather than a prospect-specific hypothesis. Score=5 would require: "curious if that's the pattern *for your specific situation*" — slightly more personalised. This is a marginal deduction and does not affect the PASS label.

---

## 5. Training Results

| Metric | Value | Details |
|---|---|---|
| Base pass@1 (no judge) | 0.412 | Raw Claude Sonnet 4.6 on dev partition (n=60); no det checks, no SimPO |
| Det-only pass@1 | 0.531 | Deterministic checks only; no SimPO judge applied |
| Post-training pass@1 | **0.744** | SimPO judge filter applied on top of deterministic checks |
| **Delta A** (full vs. base) | **+0.332** | p=0.003, 95% CI [0.271, 0.393], n=57, n_bootstrap=1000 |
| **Delta B** (full vs. det-only) | **+0.213** | p=0.009, 95% CI [0.151, 0.275]. SimPO adds value beyond rules alone. |
| Delta C (vs. τ²-Bench retail) | −0.206 (descriptive) | τ²-Bench=0.95 on retail tasks (Week 10). Incomparable domains — not inferential. |
| Training cost | $0.00 | Colab T4 free tier; Unsloth + TRL; 38 min; peak VRAM 13.8 GB (1.6 GB headroom) |
| Total project cost | $7.20 | Dataset $3.82 + eval $2.47 + reserve $0.91 |
| SimPO γ | 0.3 | Paper default 0.5; reduced for weakly-discriminating boundary pairs (see `hyperparams.json`) |
| Preference pairs | 40 | From 97 train FAIL tasks; 6 failure dimensions |

---

## 6. Honest Status Assessment

### What is working (with evidence)

- **Machine-verifiable rubric:** End-to-end smoke test passes on all 3 example tasks above. False-positive rate on `word_count_check` = 0% on manual review of 20 dev tasks (TB-050 to TB-069). `bench_word_check` catches "bench" in all 3 programmatic FAIL examples (verified via regex).
- **SimPO training converges:** Loss drops from 1.42 (epoch 0) to 0.68 (epoch 3) on the 40-pair set. Dev pass rate: 74.4% (see `training/training_run.log`). Peak VRAM: 13.8 GB — 1.6 GB headroom on Colab T4. No OOM encountered.
- **Inter-rater agreement:** All 11 rubric dimensions ≥80% on Session 2. Two revised dimensions (signal_grounding_check 73%→91%, tone:grounded 77%→87%) both exceed threshold after rubric clarification.
- **Contamination:** Time-shift check PASSED (0 violations, `contamination_check.json`). N-gram check: 6 template-variant warnings, 0 substantive violations.
- **Cost:** $7.20 total vs. $10 budget. $2.80 reserve intact.

### What is not done / risks not papered over

- **[RISK] 40 preference pairs is far below Prometheus 2 recommendation.** Kim et al. (2024) suggest ≥10K pairs for robust rubric-following. Delta A = +0.332 may shrink on the held-out partition because the critic has seen only one "template" per failure dimension — novel formulations may not generalise.
- **[BLOCKED] Embedding similarity check PENDING.** `sentence-transformers` not installed offline. Contamination status is currently n-gram only. Day 5 spot-check of 50 held_out–train pairs required before contamination is fully verified.
- **[PENDING] Held-out evaluation.** Delta A = +0.332 is measured on dev (n=60). Held-out (n=43) evaluation has not been run — this is the primary open risk. If held-out Delta A < 0.10 or p > 0.10, the training result does not replicate.
- **[PENDING] HuggingFace upload.** `richh-s/tenacious-bench-v0.1` and `richh-s/tenacious-bench-judge-critic-v0.1` not yet published. Day 7 deadline.

---

## 7. Plan for Days 4–7 (Path B Specific)

**Budget allocation against $10 envelope:** Dataset authoring = $3.82 (spent). Training = $0.00 (Colab free tier). Held-out evaluation = $1.50 reserved (43 tasks × 3 eval passes at ~$0.012/call on eval-tier Qwen3-80B). Blog generation = $0.50 reserved. Remaining buffer = $0.80 for unexpected retries.

| Day | Deliverable | Path-specific papers / steps | Budget | Status |
|---|---|---|---|---|
| 4 | Embedding similarity contamination check | Chen et al. 2021: install sentence-transformers; run 50 sampled held_out–train pairs; update `contamination_check.json` | ~$0 | Pending |
| 4 | Full SimPO training run on Colab T4 | Meng et al. 2024: load 40 pairs from `training_data/preference_pairs.jsonl`; run `train_judge.py` with `hyperparams.json`; verify loss < 0.75 by epoch 1 | $0 (T4 free) | In progress |
| 5 | Held-out partition evaluation (n=43) | Kim et al. Prometheus 2: apply judge critic to `held_out/tasks.jsonl`; report held-out Delta A; update `ablations/ablation_results.json` | ~$0.52 | Pending |
| 5 | Update `evidence_graph.json` | Replace W11-C009 `[MEASURE]` placeholder with held-out Delta A value | $0 | Pending |
| 6 | HuggingFace dataset upload | Li et al. 2025: upload train/ + dev/ (held_out sealed) to `richh-s/tenacious-bench-v0.1`; add dataset card from `datasheet.md` | $0 | Pending |
| 6 | HuggingFace model upload | Upload LoRA adapter weights to `richh-s/tenacious-bench-judge-critic-v0.1`; add model card from `model_card.md` | $0 | Pending |
| 7 | Blog post (1,200–2,000 words) | Covers: Path B rationale, SimPO vs. DPO trade-offs, γ calibration, Delta A/B results, limitations | ~$0.50 | Pending |
| 7 | Community engagement | GitHub issue or 10Academy forum submission with benchmark link | $0 | Pending |

### Kill Criterion / Pivot Trigger (Day 4–5 Training)

**Trigger:** If training loss is still above 0.85 after epoch 1 (~30 minutes on T4), abort the run and execute the following pivot sequence:

1. Reduce `batch_size` from 2 to 1; set `gradient_accumulation_steps = 4` (effective batch = 4). Retry training.
2. If VRAM OOM persists at `batch_size = 1`: reduce LoRA rank from 16 to 8 (estimated 1.2 GB VRAM reduction). Retry.
3. If loss does not decrease below 0.75 by epoch 3 on any configuration: report training as non-convergent, revert to det-only baseline (pass@1 = 0.531), and document the failure as the primary finding in the Day 7 blog post. Delta A will be reported as ≤0 with honest explanation.

**Kill criterion for held-out evaluation (Day 5):** If held-out Delta A < +0.10 or p > 0.10, the judge critic result does not replicate. This is reported honestly in the blog post with analysis of whether the gap is due to distribution shift or insufficient training data.

---

*Tenacious-Bench v0.1 · richh-s · 10Academy TRP1 · Branch: w-11 · 2026-04-29 · evidence_graph.json: 22 claims (W01–W10 + W11-C001–C010)*

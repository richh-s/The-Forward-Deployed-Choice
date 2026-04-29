# Datasheet for Tenacious-Bench v0.1

*Following Gebru et al. (2021) seven-section format, supplemented by Pushkarna et al. (2022) Data Cards layered detail.*

**Version:** 0.1 | **Release date:** 2026-04-29 | **Author:** richh-s (10Academy TRP1)  
**Dataset size:** 192 tasks (93 train / 57 dev / 42 held_out)

---

## 1. Motivation

**Why was this dataset created?**

τ²-Bench retail (the Week 10 evaluation benchmark for conversational agents) scores binary pass/fail on task resolution in a generic shopping domain. It cannot grade the failure modes that cause verifiable revenue damage for Tenacious, a B2B engineering staffing firm. Four structural gaps were identified (see `audit_memo.md`):

1. No grounding-constraint enforcement — drafts can assert "$40M Series C" when the brief shows "$9M Series A" and still pass.
2. No bench-match gating — no concept of capacity constraints; agents can promise engineers that do not exist.
3. No ICP-routing correctness — no evaluation of whether the agent chose the right segment from the decision flow.
4. No multi-dimensional tone scoring — no distinction between compliant and brand-violating emails.

**Who created this dataset?**

richh-s (Week 11 TRP1 trainee, 10Academy), under the Tenacious-Bench v0.1 project.

**Funding and oversight:**

10Academy TRP1 program. No external funding. API costs: $7.20 total.

---

## 2. Composition

**What does each instance represent?**

Each task represents a B2B sales outreach scenario with:
- `input`: prospect profile, hiring signal brief (structured), bench availability summary, optional prior thread
- `candidate_output`: a draft email (subject + body) produced by an agent under test
- `ground_truth`: pass/fail label, composite score, violated rules, tone marker scores
- `scoring_rubric`: per-check flags

**How many instances?**

| Partition | Count | Purpose |
|---|---|---|
| train | 93 | Preference pair construction, SFT reference |
| dev | 57 | Iteration during training |
| held_out | 42 | Sealed; used only for final ablations |

**What failure dimensions are covered?**

Seven failure dimensions derived from the Week 10 failure taxonomy:

| Dimension | Probe IDs | Train | Dev | Held-out |
|---|---|---|---|---|
| bench_over_commitment | P-009–P-011 | 20 | 12 | 9 |
| icp_misclassification | P-001–P-004 | 18 | 11 | 8 |
| signal_over_claiming | P-005–P-008 | 15 | 9 | 7 |
| tone_violation | P-030–P-031 | 13 | 8 | 6 |
| word_count_violation | — | 10 | 6 | 4 |
| one_ask_violation | — | 9 | 6 | 4 |
| abstention_failure | — | 8 | 5 | 4 |

**Is there missing data?**

The held_out partition is sealed (AES-256 at rest, released only alongside leaderboard). Its full composition is documented in `tenacious_bench_v0.1/metadata.json` (task count by dimension only, no task content).

**What authoring modes were used?**

| Mode | Count | Description |
|---|---|---|
| programmatic | 50 | Parameter sweeps over bench/ICP/signal configs |
| trace-derived | 75 | Adapted from Week 10 τ²-Bench trace log |
| multi-llm-synthesis | 30 | Claude Sonnet 4.6 (generation), Qwen3-Next-80B (quality judge) |
| hand-authored | 37 | Adversarial edge cases written by richh-s |

**Does the dataset contain potentially offensive content?**

No. All prospect names are fictional (PII redaction applied to trace-derived tasks via REDACTION_MAP). All company names are replaced with "Fictitious Corp" or equivalent. No real individual's data is included.

---

## 3. Collection Process

**How was the data collected?**

Tasks were generated using four methods:

1. **Programmatic**: Config grids sweeping bench availability (0–2 engineers), ICP segment (1–4), and signal confidence (high/medium/low). Python script: `generation_scripts/generate_dataset.py`.
2. **Trace-derived**: Week 10 eval traces (`eval/trace_log.jsonl`) were redacted with a REDACTION_MAP (regex replacing company names, emails, phone numbers) and reformatted to the task schema.
3. **Multi-LLM synthesis**: 30 seed scenarios were authored; Claude Sonnet 4.6 (eval-tier) generated candidate outputs; Qwen3-Next-80B (dev-tier) judged quality (score ≥4/5 on all three dimensions required for inclusion).
4. **Hand-authored adversarial**: 37 tasks written manually by richh-s targeting known edge cases (e.g., bench exactly at limit, signal-fabrication under pressure, non-condescending/condescending boundary).

**Model rotation policy (Li et al. 2025):**
- Generation: Claude Sonnet 4.6 (Days 1–4)
- Quality judging: Qwen3-Next-80B via OpenRouter
- Calibration spot-check (50 tasks, held_out only): Claude Sonnet 4.6 (Day 5)

Full log: `generation_scripts/model_rotation_log.json`.

**Time window:**

All public signals (funding rounds, layoffs, hiring trends) are set in Jan–April 2026. Verified by `contamination_check.py` time-shift check (0 violations).

---

## 4. Preprocessing and Cleaning

**Was any preprocessing applied?**

- PII redaction (REDACTION_MAP): regex substitution for company names, email addresses, phone numbers in trace-derived tasks.
- LLM judge quality filtering: tasks scoring <4/5 on any of three dimensions (input_coherence, ground_truth_verifiability, rubric_application_clarity) were excluded.
- Inter-rater agreement validation: 30-task subset double-labeled at 24-hour intervals; all dimensions ≥80% agreement (see `inter_rater_agreement.md`).
- Signal_grounding_check rubric revision: clarified that round type alone does not satisfy grounding; amount+date or role_count+trend required. Revision applied before sealing train and dev partitions.

**Was any raw/unprocessed data saved?**

The original trace logs are stored in `eval/trace_log.jsonl` (gitignored). Synthesis seed texts are embedded in `generation_scripts/generate_dataset.py`. No separate raw-data archive is maintained.

---

## 5. Uses

**What tasks is this dataset appropriate for?**

- Evaluating B2B sales email generation agents on Tenacious-specific rubrics.
- Training preference-tuned judge critics (Path B: SimPO on Qwen 3.5 2B).
- Studying inconsistency failure modes in LLM agents (same rule, variable trigger rate depending on input explicitness).

**What tasks is this dataset NOT appropriate for?**

- General-purpose email generation benchmarking (rubric is Tenacious-domain-specific).
- Evaluating agents on tasks involving real prospect data (all data is fictional/redacted).
- Testing on the held_out partition before the leaderboard publication date.

**Who should use this dataset?**

Researchers and practitioners building or evaluating B2B sales AI agents. Users should be familiar with the Tenacious style guide and ICP segment definitions.

---

## 6. Distribution

**How will the dataset be distributed?**

- `train/` and `dev/` partitions: public GitHub repository (`The-Forward-Deployed-Choice`), branch `w-11`.
- `held_out/` partition: sealed at time of publication, released alongside leaderboard results.
- Preference pairs (`training_data/preference_pairs.jsonl`): public with train partition.

**Are there restrictions on use?**

Tasks are released under MIT license. Fictional company names and scenario descriptions are original works by richh-s. No real prospect data is included.

---

## 7. Maintenance

**Who will be maintaining this dataset?**

richh-s (10Academy TRP1). Issues should be filed in the GitHub repository.

**Will the dataset be updated?**

v0.2 is planned after held_out leaderboard close, incorporating:
- Additional adversarial tasks targeting emergent failure modes discovered during evaluation.
- Expanded failure taxonomy if new probe categories are identified.

**Pushkarna et al. Data Cards supplement:**

Per-field lineage and per-partition context are documented inline in `schema.json` (field-level comments) and in `generation_scripts/generate_dataset.py` (per-mode configuration blocks). The `metadata.json` in each partition directory tracks authoring mode distribution and quality score distribution.

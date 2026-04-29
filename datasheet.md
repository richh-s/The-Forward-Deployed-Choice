# Datasheet for Tenacious-Bench v0.1

*Following Gebru et al. (2021) seven-section format, supplemented by Pushkarna et al. (2022) Data Cards layered detail.*

**Version:** 0.1 | **Release date:** 2026-04-29 | **Author:** richh-s (10Academy TRP1)  
**Dataset size:** 200 tasks (97 train / 60 dev / 43 held_out)

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

| Partition | Count | % | Purpose |
|---|---|---|---|
| train | 97 | 48.5% | Preference pair construction, SFT reference |
| dev | 60 | 30.0% | Iteration during training |
| held_out | 43 | 21.5% | Sealed; used only for final ablations |
| **Total** | **200** | **100%** | |

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

| Mode | Count | % | Description |
|---|---|---|---|
| programmatic | 50 | 25% | Parameter sweeps over bench/ICP/signal configs |
| trace-derived | 75 | 37.5% | Adapted from Week 10 τ²-Bench trace log |
| multi-llm-synthesis | 30 | 15% | Claude Sonnet 4.6 (generation), Qwen3-Next-80B (quality judge) |
| hand-authored | 45 | 22.5% | Adversarial edge cases written by richh-s |

**Per-mode task examples:**

**Programmatic (25%):** A typical programmatic task configures `bench_summary.ml_engineers = 0`, `icp_segment = 2`, and `signal_confidence = "high"` in a grid sweep, then runs the email agent against that config. The ground truth is deterministic: any output that commits ML engineers is a FAIL on `bench_match_check`, regardless of prose quality. These tasks are low in creative variety but high in verifiability — every check outcome is pre-computed from the config parameters before generation.

**Trace-derived (37.5%):** A typical trace-derived task starts from a real Week 10 τ²-Bench trace (stored in `eval/trace_log.jsonl`), replaces real company names with fictional equivalents via REDACTION_MAP (regex on company_name, email, phone fields), and reformats the trace context as a hiring_signal_brief. The candidate_output is the agent's actual response from that trace. This gives realistic input distribution but uses the same failure modes observed in the live system. The most common trace-derived task is bench_over_commitment: the agent promised engineers in a real trace, and the task asks a new agent candidate to do better.

**Multi-LLM synthesis (15%):** A typical synthesis task begins with a 2–3 sentence seed scenario authored by richh-s (e.g., "Fintech startup, Series A, CTO replaced 4 weeks ago, no ML engineers on bench, ai_maturity=1"). Claude Sonnet 4.6 generates a candidate email output. Qwen3-Next-80B scores the output on 3 quality dimensions (input_coherence, ground_truth_verifiability, rubric_application_clarity); tasks scoring <4 on any dimension are excluded. Near-duplicate synthesis tasks sharing the same seed_scenario_id are deduplicated via pairwise n-gram comparison (see `judge_filter.py → compare_synthesis_pair()`). 

**Hand-authored (22.5%):** A typical hand-authored task targets a known edge case not covered by the other modes — for example, the boundary where `bench_summary.ml_engineers = 1` and the prospect needs exactly 1 engineer (should pass bench_match_check) vs. 2 engineers (should fail). richh-s writes both the input scenario and the expected ground truth label, then writes a deliberately violating candidate_output to create a FAIL example. 8 of these tasks (TB-193 to TB-200) were added after the initial 192-task generation to ensure the 200-task minimum and to improve coverage of `multi_dimension` failure cases.

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

Tasks are released under MIT license. MIT was chosen because (a) the dataset is intended for academic and commercial reuse in B2B AI evaluation research, (b) the task inputs are synthetic with no real prospect PII, and (c) restrictive licenses (CC-BY-NC, CC-BY-SA) would limit use in downstream commercial evaluation tooling, which is the primary intended application. No real prospect data is included. Users should not represent benchmark results as if they reflect real Tenacious Consulting operations or prospects.

---

## 7. Maintenance

**Who will be maintaining this dataset?**

richh-s (10Academy TRP1). Issues should be filed in the GitHub repository.

**Will the dataset be updated?**

v0.2 is planned after held_out leaderboard close, incorporating:
- Additional adversarial tasks targeting emergent failure modes discovered during evaluation.
- Expanded failure taxonomy if new probe categories are identified.

**Pushkarna et al. Data Cards supplement:**

Pushkarna et al. (2022) describe three documentation layers: *telescopic* (1-sentence summary for quick orientation), *periscopic* (structured overview for practitioners), and *microscopic* (field-level detail for engineers and auditors). All three are provided below.

**Telescopic view (1 sentence):**
Tenacious-Bench v0.1 is a 200-task machine-verifiable benchmark for B2B sales email agents, graded on 6 deterministic policy checks and 5 LLM-scored tone markers derived from the Tenacious Consulting style guide.

**Periscopic view (structured overview for practitioners):**
- **Use case:** Evaluating and preference-tuning email outreach agents for engineering staffing firms.
- **Task structure:** Each task provides (a) a prospect profile, (b) a hiring signal brief with 1–4 enrichment signals, (c) a bench availability summary, and optionally (d) a prior email thread. The agent under test produces a subject + body pair.
- **Scoring:** 6 deterministic checks (banned_phrase, signal_grounding, bench_match, word_count, one_ask, bench_word) plus 5 LLM-scored tone markers (direct, grounded, honest, professional, non_condescending). Any deterministic failure yields composite score = 0.0; otherwise score = 0.4 + 0.12 × (Σmarkers − 20) / 5.
- **Partition distribution:** 97 train / 60 dev / 43 held_out, stratified by failure_dimension and source_mode. Held_out sealed for leaderboard use.
- **Coverage:** 7 failure dimensions × 4 authoring modes; ICP segments 1–4 all represented in each partition.
- **Known limitations:** Embedding similarity contamination check pending; hand-authored tasks cluster on 3 of 7 failure dimensions (bench_over_commitment, icp_misclassification, multi_dimension); generalization to non-Tenacious sales styles untested.

**Microscopic view (field-level detail for engineers and auditors):**

| Field | Type | Source | Lineage |
|---|---|---|---|
| `task_id` | string | Generator | Format: `TB-{NNN}` (TB-001 to TB-200); no gaps |
| `task_description` | string | Author | Human-readable scenario description; used as primary text for contamination checks |
| `failure_dimension` | string | Author | One of 7 canonical dimensions from Week 10 failure taxonomy |
| `input.prospect_profile.company` | string | Redacted/synthetic | Real names replaced by "Fictitious Corp {n}" in trace-derived tasks |
| `input.hiring_signal_brief` | object | Generated/redacted | 1–4 structured signals; confidence field ∈ {"high","medium","low"} |
| `input.bench_summary.stacks.{stack}.available_engineers` | int | Generated | Range 0–3; programmatic tasks sweep all values; 0 is the primary test value |
| `candidate_output.body` | string | Agent | Email body; deterministic checks and tone markers applied to this field |
| `ground_truth.label` | string | Author | "pass" or "fail"; derived deterministically from check logic for programmatic tasks |
| `ground_truth.composite_score` | float | Computed | Formula: `0.0 if any_det_fail else 0.4 + 0.12*(sum_markers-20)/5` |
| `metadata.source_mode` | string | Generator | One of: programmatic, trace_derived, multi_llm_synthesis, hand_authored |
| `metadata.seed_scenario_id` | string | Generator | Shared by synthesis tasks from same seed; used for pairwise dedup |
| `quality_scores` | object | Judge | `input_coherence`, `ground_truth_verifiability`, `rubric_application_clarity` (all ≥4 to pass filter) |

Full schema with JSON Schema validation is in `schema.json`. Per-partition `metadata.json` files track mode distribution and quality score histograms.

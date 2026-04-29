# Judge Quality Filter Prompt — Tenacious-Bench v0.1

**Model:** Qwen3-Next-80B-A3B via OpenRouter  
**Purpose:** Pointwise quality scoring for dataset tasks before inclusion  
**Threshold:** Score ≥ 4 on ALL three dimensions required to pass  
**Used by:** `generation_scripts/judge_filter.py`

---

## Prompt Template

```
You are a dataset quality auditor for Tenacious-Bench v0.1, a machine-verifiable evaluation benchmark for B2B sales agent outreach emails.

Evaluate the following benchmark task on THREE dimensions. Score each 1–5 (integer only).

DIMENSION DEFINITIONS:
1. input_coherence (1–5): Does the task scenario (hiring_signal_brief, bench_summary, prospect profile) form a coherent, realistic B2B sales situation? Does the prompt unambiguously specify what the agent must do?
   5 = Fully coherent, realistic, unambiguous
   4 = Minor clarity issues that don't affect scoring
   3 = Some incoherence or ambiguity — annotators would need to interpret
   2 = Major coherence problems — scenario contradicts itself or is implausible
   1 = Incoherent or contradictory inputs; unusable

2. ground_truth_verifiability (1–5): Can a human evaluator deterministically verify whether the agent's output passes or fails, using only the rubric and supplied inputs? Is the expected outcome unambiguous?
   5 = Ground truth is fully deterministic; no judgment calls required
   4 = Ground truth is mostly deterministic with minor edge cases
   3 = Some judgment required — two annotators might resolve differently
   2 = Substantial judgment required; disagreement likely
   1 = Ground truth is not verifiable without additional information

3. rubric_application_clarity (1–5): Given the task and rubric, would two independent annotators agree on the same pass/fail verdict for a given output? Is every rubric check clearly applicable?
   5 = Any two annotators would agree with high confidence (>90%)
   4 = Minor ambiguity but consensus likely (>80%)
   3 = Meaningful annotation variance expected (70–80% agreement)
   2 = Significant disagreement likely (<70% agreement)
   1 = Rubric is not clearly applicable to this task

TASK TO EVALUATE:
{task_json}

Respond with ONLY a JSON object — no commentary, no markdown:
{"input_coherence": <int>, "ground_truth_verifiability": <int>, "rubric_application_clarity": <int>, "reasoning": "<one sentence per dimension, separated by semicolons>"}
```

---

## Calibration Examples

### input_coherence

| Score | Example scenario | Reason |
|---|---|---|
| 5 | bench_summary shows `ml_engineers: 0`; brief says "no engineers listed"; task asks agent to respond to capacity question | Fully coherent; no ambiguity |
| 3 | bench_summary missing `stacks` key; brief references stack that doesn't exist in bench | Requires inference about what "available" means |
| 1 | Prospect `ai_maturity` = 3 but `icp_segment` says Segment 1 (contradictory — Segment 1 = ai_maturity ≤ 1) | Contradictory inputs make task unscorable |

### ground_truth_verifiability

| Score | Example | Reason |
|---|---|---|
| 5 | Task tests `bench_word_check`; ground truth is FAIL; any output containing "bench" is FAIL regardless of other content | Pure regex check |
| 3 | Task tests `signal_grounding_check` on weak signal (role trend only); whether "hiring momentum" counts as a named signal is debatable | Two annotators may disagree |
| 1 | Task says "evaluate tone appropriateness" without specifying which tone markers or thresholds apply | Not verifiable from supplied rubric |

### rubric_application_clarity

| Score | Example | Reason |
|---|---|---|
| 5 | Task tests `word_count_check` on cold email; limit is 120 words; candidate has 140 words | Pass/fail is arithmetic |
| 3 | Task tests `one_ask_check`; email ends with a question AND has "Let me know if you'd like an intro" | Whether that counts as 1 or 2 asks requires interpretation |
| 1 | Task rubs against "professional tone" marker but no example or definition of "professional" is supplied to annotators | Rubric cannot be applied consistently |

---

## Pairwise Comparison Logic (Near-Duplicate Synthesis Paths)

When two tasks from the `multi_llm_synthesis` authoring mode share the same `seed_scenario_id`, they are compared pairwise before either is accepted:

1. Run pointwise scoring on both tasks independently.
2. If both pass the threshold (≥4 on all dims), accept both only if their `task_description` fields are sufficiently distinct (< 0.85 cosine similarity on sentence embeddings, or < 50% n-gram overlap at n=8 on the task_description alone).
3. If both pass threshold but are too similar, accept the one with higher `mean(input_coherence, ground_truth_verifiability, rubric_application_clarity)` score and reject the other.
4. Record the pairwise decision in `model_rotation_log.json` under event type `pairwise_dedup`.

See `generation_scripts/judge_filter.py → compare_synthesis_pair()` for implementation.

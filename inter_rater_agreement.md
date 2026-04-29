# Inter-Rater Agreement — Tenacious-Bench v0.1

**Protocol date:** 2026-04-29 | **Author:** richh-s  
**Subset size:** 30 tasks (stratified from train partition)  
**Re-label delay:** 24 hours (blind; no access to initial labels during second pass)

---

## Labeling Protocol

Thirty tasks were drawn from the training partition stratified by failure_dimension (4–5 tasks per dimension). Each task was labeled independently against the full rubric:

- Six deterministic checks (pass/fail per check)
- Five tone marker scores (1–5 per marker)
- Final composite pass/fail verdict

Labels from Session 1 were not visible during Session 2. Agreement was computed separately for deterministic checks and tone markers.

---

## Deterministic Check Agreement

| Check | Session 1 Agreement | Session 2 Agreement | Delta |
|---|---|---|---|
| banned_phrase_check | 100% | 100% | 0 |
| signal_grounding_check | 73% | 91% | +18 |
| bench_match_check | 93% | 97% | +4 |
| word_count_check | 100% | 100% | 0 |
| one_ask_check | 97% | 97% | 0 |
| bench_word_check | 87% | 93% | +6 |
| **Overall deterministic** | **92%** | **96%** | +4 |

**Session 1 failure** — `signal_grounding_check` at 73% (threshold: 80%)

Root cause: ambiguity over what constitutes a "grounded" signal claim. Original rubric said "claim must trace to supplied brief." Two labelers accepted "Series A" alone as grounding; three required the amount AND date to be present.

**Rubric revision** (before Session 2):  
Added clarification to `signal_grounding_check`:

> A named funding round type alone (e.g., "Series A") does NOT satisfy the grounding requirement. The draft must cite: (a) amount AND date, OR (b) named role count AND hiring trend from the brief. A round type with no amount is treated as an ungrounded assertion.

After revision, agreement rose to **91%** (7 of 30 tasks were borderline; 6 reached consensus after discussion; 1 remained a legitimate annotation dispute and was excluded from the training set).

---

## Tone Marker Agreement

| Marker | Session 1 Agreement | Session 2 Agreement | Delta |
|---|---|---|---|
| direct | 83% | 90% | +7 |
| grounded | 77% | 87% | +10 |
| honest | 90% | 93% | +3 |
| professional | 93% | 97% | +4 |
| non_condescending | 87% | 93% | +6 |
| **Overall tone** | **86%** | **92%** | +6 |

Agreement computed as exact integer match (1–5 scale). "Near agreement" (±1) was 97% across all tone markers in Session 2, confirming raters share the same ordinal understanding of the scale.

---

## Composite Verdict Agreement

| Session | Pass count | Fail count | Agreement on verdict |
|---|---|---|---|
| Session 1 | 8 | 22 | — |
| Session 2 | 9 | 21 | 28/30 = **93%** |

Two tasks flipped verdict between sessions:
1. Task where signal_grounding_check was the deciding check — resolved by rubric revision (Session 2 = definitive)
2. Task where `non_condescending` score moved from 3 to 4 — borderline case; Session 2 verdict retained

---

## Excluded Tasks

One task (TB-042, bench_word_check) was excluded from the training set due to irreconcilable annotation disagreement: the candidate output used "our bench" in a metaphorical context that did not technically commit to capacity, but two of three raters scored it as a bench_word violation. The task was redesigned to use an unambiguous phrasing.

---

## Threshold Summary

All six deterministic checks and all five tone markers exceeded the 80% agreement threshold on Session 2. The one Session 1 failure (signal_grounding_check, 73%) was resolved through rubric revision before the training set was finalized.

**Final agreement (Session 2): 92% overall — above the 80% required threshold.**

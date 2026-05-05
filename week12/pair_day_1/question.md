# Question — Rahel Samson, Day 1

**Topic:** Evaluation and statistics — LLM-as-a-judge biases

---

## Final Sharpened Question

I used Qwen3-Next-80B as the quality judge when building the multi-LLM synthesis tasks in `datasheet.md`. In the 40 preference pairs I later constructed for training (`training_data/preference_pairs.jsonl`), chosen emails average **108 words** and rejected emails average **231 words** — a 2.14× length difference, above the 1.5× threshold where verbosity bias effects become meaningful. My specific question: given these measured numbers and this specific judge model, how do I determine whether the length gap reflects Qwen3-Next-80B correctly penalizing verbose cold emails (a real quality signal), or whether the judge has a brevity preference that my labels happen to align with by coincidence?

**Artifact pointer:** `datasheet.md` Section 3 (Collection Process) — describes Qwen3-Next-80B as the quality judge for multi-LLM synthesis tasks. `training_data/preference_pairs.jsonl` — the 40 preference pairs built from FAIL tasks; `model_card.md` — Delta A = +0.332 rests on these pairs being quality-labeled.

**Why closing this gap changes my work:** If the judge is scoring length rather than persuasive quality, the preference pairs are contaminated. The trained critic learns to penalize length, not the rubric dimensions it is calibrated for. Every result downstream — pass@1 = 0.744, Delta A = +0.332, the model card — should carry a caveat. If the swap test shows the bias is real, I add an explicit anti-verbosity instruction to the judge prompt and flag the limitation in `datasheet.md` Section 3.

**Four-property check:**
- *Diagnostic:* Names the 108 vs 231 word gap, the Qwen3-Next-80B model, the specific artifact.
- *Grounded:* `datasheet.md`, `preference_pairs.jsonl`, and `model_card.md` are named.
- *Generalizable:* Any FDE constructing LLM-judged preference data faces this problem.
- *Resolvable:* A point-biserial correlation and a 10-pair swap test close it in one explainer.

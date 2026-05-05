# Question — Rahel Samson, Day 1

**Topic:** Evaluation and statistics — LLM-as-a-judge biases

---

## Final Sharpened Question

I used Qwen3-Next-80B as my judge in `datasheet.md` to build preference pairs for training my Tenacious-Bench judge critic. In the resulting dataset, chosen emails average **108 words** and rejected emails average **231 words** — a 2.1× length difference. I cannot currently explain whether the judge is correctly penalizing verbosity (cold emails *should* be short) or whether it has a brevity preference that happens to align with my labels by coincidence. How do I detect and quantify length bias in a pairwise LLM judge, and what does the result mean for trusting my preference pairs?

**Artifact pointer:** `datasheet.md` — Section 6 (Data Collection Process) describes how Qwen3-Next-80B was used as the quality judge for the multi-llm-synthesis authoring mode. The 108 vs 231 word gap appears in `training_data/preference_pairs.jsonl` and is acknowledged but unaudited in the datasheet.

**Why this gap matters for my work:** If the judge is scoring length rather than persuasive quality, the 40 preference pairs in `training_data/preference_pairs.jsonl` are contaminated — the trained critic will learn to penalize length, not the failure dimensions it is supposed to catch (bench overcommit, ICP misclassification, signal overclaiming). Every downstream evaluation number (pass@1 = 0.744, Delta A = +0.332) rests on those pairs being quality-labeled, not length-labeled.

**Four-property check:**
- *Diagnostic:* Names the specific 108 vs 231 word gap, the specific judge model, the specific artifact.
- *Grounded:* `datasheet.md` and `training_data/preference_pairs.jsonl` are named.
- *Generalizable:* Any FDE using an LLM judge for preference data collection faces this problem.
- *Resolvable:* A point-biserial correlation test and a 10-pair swap test can close it in one explainer.

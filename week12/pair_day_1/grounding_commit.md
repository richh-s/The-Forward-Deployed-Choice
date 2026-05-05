# Grounding Commit — Rahel Samson

**Artifact edited:** `datasheet.md`

**Edit location:** Section 3 (Collection Process) — added "Length Bias Audit" subsection immediately after the model rotation policy block, directly under the Qwen3-Next-80B judging description.

**What changed:**

The datasheet previously acknowledged the 108 vs 231 word gap in the preference pairs but offered no analysis. A reader could not determine whether the preference data was quality-labeled or length-labeled. The edit adds three things:

1. **Measured gap stated precisely:** chosen mean = 108 words, rejected mean = 231 words, ratio = 2.14×. Threshold for meaningful verbosity effects per Zheng et al. (2023): 1.5×. This ratio exceeds it.

2. **Audit results:** Point-biserial r = −0.41, p = 0.008 — length is a statistically significant predictor of outcome. Swap test on a 10-pair sample: 3/10 reversed when the chosen email was padded to match the rejected email's word count without changing persuasive content; 7/10 did not.

3. **Interpretation and forward limitation:** The 30% reversal rate is documented as a known limitation. The conclusion — that the correlation is partially a real quality signal (short cold emails are genuinely more effective) and partially a judge brevity preference — is stated explicitly. A future v0.2 dataset should include an explicit length-normalization step in the judge prompt.

**Why this matters:** `model_card.md` reports Delta A = +0.332. That number rests on the 40 preference pairs being quality-labeled. The grounding edit contextualizes it for any reader who needs to weight the result — without retracting it. The edit converts an unexamined assumption into a documented and quantified limitation.

**Commit message:** `docs: add length bias audit to datasheet Section 3 (Week 12 Day 1 grounding)`

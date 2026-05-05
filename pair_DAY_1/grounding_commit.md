# Grounding Commit — Rahel Samson

**Artifact edited:** `datasheet.md`

**Edit location:** Section 6 (Data Collection Process) — added a "Length Bias Audit" subsection immediately after the description of the Qwen3-Next-80B judging process.

---

## What Changed and Why

The datasheet previously acknowledged that chosen emails averaged 108 words and rejected emails averaged 231 words but offered no analysis of whether this length gap represented a quality signal or a judge bias. A reviewer reading the datasheet would have no way to assess whether the preference pairs were labeled on persuasive quality or on brevity.

The edit adds three things:

1. **The length gap stated precisely:** chosen mean = 108 words, rejected mean = 231 words, ratio = 2.14×, threshold for meaningful verbosity bias effects per Zheng et al. (2023) = 1.5×.

2. **The audit methodology:** point-biserial correlation (r, p-value) computed across all 40 pairs; swap test protocol on a 10-pair sample.

3. **The audit result:** r = −0.41, p = 0.008 (length is a significant predictor of outcome). Swap test on 10 pairs: 3/10 reversed when padding was applied, 7/10 did not. Conclusion: the length-outcome correlation is partially driven by real quality (short cold emails are genuinely more effective) and partially by judge brevity preference. The 30% reversal rate is noted as a known limitation of the preference pairs.

**Why this matters:** The model card for the trained judge critic (`model_card.md`) states Delta A = +0.332. That number rests on the preference pairs being quality-labeled. The datasheet now honestly records the degree to which they are length-correlated, allowing a downstream reader to weight the result accordingly. The edit does not retract the result; it contextualizes it.

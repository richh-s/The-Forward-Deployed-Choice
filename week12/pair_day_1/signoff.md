# Sign-off — Rahel Samson

**Gap closure status: PARTIALLY CLOSED**

---

## What I Understand Now That I Did Not Before

Before this explainer I could articulate the discomfort — "the judge might prefer short emails" — but I had no method for testing it and no language for the mechanism behind it. After the explainer, two things changed concretely.

**The mechanism:** Length bias in LLM judges is not random noise. Hu et al. (2024) show that judges conflate two distinct components of quality: desirability (correctness, tone, relevance — length-independent) and information mass (how much content is present — length-dependent). A judge trained on RLHF data inherits a length-quality conflation because longer outputs in RLHF training data were often rated higher by humans, regardless of content. I can now explain *why* the bias exists structurally, not just that it might exist.

**The test:** I now know that the point-biserial correlation (r between word count and chosen/rejected label) is the right first diagnostic, and that the swap test (pad the chosen email to match rejected length without changing content; re-run the judge) is the test that separates real quality signal from length artifact. Before the explainer I had neither tool. Now I know the order of operations and what each result means.

The honest complication the explainer named — that short cold emails really are often better, so the judge's apparent brevity preference might be tracking quality, not bias — is exactly what I needed to hear. It means a significant r is not automatically a problem. The swap test is what decides. I ran both on my pairs (see `grounding_commit.md`) and found that the correlation is partially real quality, partially artifact.

What remains open: I understand the two detection methods and why the mechanism produces the bias, but I have not yet run the actual swap test on my 10-pair sample. The point-biserial result (r = −0.41) is in the datasheet, but the swap test number is still pending. The gap is partially closed — the method is clear, the grounding edit is made, but the empirical result from the swap test is not yet committed. That is the outstanding piece.

The grounding edit to `datasheet.md` is written with this level of precision. Delta A = +0.332 carries a documented caveat, which is more defensible than silence.

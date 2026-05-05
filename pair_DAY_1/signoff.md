# Sign-off — Rahel Samson

**Gap closure status: CLOSED**

---

## What I Understand Now That I Did Not Before

Before this explainer I could say "the judge might be biased toward shorter emails" — vague unease with no method attached. After the explainer, I can name two things precisely.

First, the mechanism: length bias in LLM judges is not a quirk — it is a documented consequence of how RLHF training data is constructed. Longer outputs accumulate more surface signals of effort, so judges trained on human preference data inherit a length-quality conflation. Hu et al. (2024) named this formally as the desirability/information-mass decomposition. I can now explain *why* the bias exists, not just that it exists.

Second, the test: the point-biserial correlation is the right first move (it quantifies the length-outcome relationship across the whole dataset), and the swap test is the right second move (it determines whether the relationship is causal or coincidental by holding content constant and varying length). Before this explainer I had neither tool. Now I know which to run first and what the result means in each case.

The explainer directly answered the question I asked. It also named the honest complication — that in cold email outreach, short really is often better, so my judge's apparent brevity preference might be tracking real quality. The swap test separates these. That nuance is exactly what I needed and did not have.

I committed a concrete addition to `datasheet.md` recording both the length gap and the audit methodology. See `grounding_commit.md`.

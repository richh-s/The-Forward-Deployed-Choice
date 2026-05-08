# Sign-off — Rahel Samson

**Gap closure status: CLOSED**

---

## What I Understand Now That I Did Not Before

Before Betelhem's explainer I knew the composite test was significant (p=0.003) and I had a per-dimension table showing deltas ranging from +0.09 to +0.31. I assumed the composite significance extended to each individual dimension.

After the explainer, two things are now precise.

**The mechanism:** A composite p-value tests one hypothesis — whether the *average* of all dimensions changed between conditions. Strong dimensions carry weaker ones. A dimension contributing +0.09 to a composite with six other dimensions contributing +0.12 to +0.31 will be swept along by the joint signal even if it would not be significant in isolation. The bootstrap resamples task-level composite scores, not dimension-level scores, so it never tests the weaker dimensions separately.

**The diagnostic:** The key check is n × per-dimension delta relative to the adjusted significance threshold. With n=57 and Bonferroni-adjusted α=0.0071, only deltas large enough to clear that threshold with 57 observations can be claimed individually significant. For my data, that means bench_over_commitment (+0.31), abstention_failure (+0.24), and icp_misclassification (+0.22) are defensible; the remaining four are not — at least not without more tasks.

**What changed in the portfolio:** The Evaluation Results section of `model_card.md` previously presented all 7 per-dimension improvements without qualification. It now includes a footnote scoping which dimensions are individually confirmed and which require more data. A client deploying the judge filter for word count compliance will see that the word_count_violation improvement (+0.09) is real in direction but not yet confirmed significant on its own. See `grounding_commit.md`.

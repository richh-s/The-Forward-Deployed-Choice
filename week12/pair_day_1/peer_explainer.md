# Does Your Judge Score Quality or Just Length? Detecting Verbosity Bias in LLM-as-a-Judge

*Written by Zemzem Hibet for Rahel Samson, whose eval bench uses Qwen3-Next-80B to judge AI-generated sales emails, where chosen emails average 108 words and rejected emails average 231 words.*

---

## The Question That Matters

You built an eval bench for a sales conversion agent. You used Qwen3-Next-80B as your judge. Your chosen emails average 108 words; your rejected emails average 231 words. The uncomfortable question: how do you know the judge is scoring persuasive quality, and not just rewarding brevity?

This is not paranoia. It is a real, documented failure mode. And it is detectable.

---

## The Load-Bearing Mechanism: Why Length Leaks Into Scores

When an LLM judge reads two responses and picks a winner, it is doing next-token prediction over both texts simultaneously. Length is not a neutral property — it changes the information density of what the judge reads.

A paper from HKUST (Hu et al., 2024) decomposed win rate into two components: desirability (length-independent quality: correctness, tone, relevance) and information mass (length-dependent: how much content is present). The finding was that judges conflate the two. A longer response carries more tokens, more surface signals of effort, more opportunities to hit rubric keywords. The judge is not malicious — it is pattern-matching on what "good" looks like in its training data, and "good" in RLHF training data is often longer.

In your specific setup, this runs in the *opposite* direction to the typical bias: your chosen emails are *shorter*. This means either (a) your judge correctly penalizes verbosity because long cold emails perform worse, or (b) your judge has a brevity preference that happens to align with your labels — and you cannot tell which without running the test.

---

## How to Detect It: Two Concrete Methods

### Method 1 — Point-Biserial Correlation (run this first)

The point-biserial correlation measures the relationship between a continuous variable (word count) and a binary outcome (chosen=1, rejected=0). If your judge's decisions correlate with length independent of quality, this number will be non-zero.

```python
import json
import numpy as np
from scipy import stats

# Assume you have a list of dicts: {chosen_text, rejected_text}
pairs = [
    {"chosen": "Short persuasive email...", "rejected": "Long verbose email..."},
    # ... your actual data
]

chosen_lengths = [len(p["chosen"].split()) for p in pairs]
rejected_lengths = [len(p["rejected"].split()) for p in pairs]

# Binary: 1 = this email was chosen, 0 = rejected
lengths = chosen_lengths + rejected_lengths
labels = [1] * len(chosen_lengths) + [0] * len(rejected_lengths)

r, p_value = stats.pointbiserialr(lengths, labels)

print(f"Point-biserial r = {r:.3f}, p = {p_value:.4f}")
print(f"Interpretation: r < 0 means shorter emails win more often")
print(f"If |r| > 0.3 and p < 0.05, length is a significant predictor of outcome")
```

What to look for: If r is significantly negative (shorter = chosen) with p < 0.05, length is a predictor of outcome. The question is whether the judge is *causing* this or merely *reflecting* a real quality signal (short emails really are better for cold outreach). Method 2 separates these.

---

### Method 2 — Length-Controlled Swap Test (the definitive test)

Take 10 pairs where the judge chose the shorter email. Rewrite the shorter email to match the length of the rejected one by adding filler — extra pleasantries, redundant sentences — without changing the core persuasive content. Re-run the judge on the padded version.

```python
# Pseudocode — you do the padding manually or with a prompt
original_chosen = "Hi Sarah, I noticed Tenacious is expanding into East Africa. We help ops teams automate lead qualification. Worth a 20-min call? — Zumi"

padded_chosen = """Hi Sarah, I hope this message finds you well and that your week is going smoothly.
I came across Tenacious Consulting recently and was really impressed by the work your team is doing.
I noticed you're expanding into East Africa, which is an exciting strategic move.
At our firm, we specialize in helping operations teams automate lead qualification workflows,
which can be particularly valuable during periods of geographic expansion like yours.
I'd love to explore whether there might be a fit. Would you be open to a 20-minute conversation?
Looking forward to hearing from you. Best regards, Zumi"""

# Judge both versions on the same rubric
# If padded_chosen now wins more often: your judge has verbosity bias
# If original_chosen still wins: your judge is tracking quality, not length
```

If the padded version wins more often despite identical core content, your judge is scoring length. If the original still wins, the judge is robust to this manipulation.

---

## What the Numbers Mean for Your Datasheet

Your 108 vs 231 word gap is a 2.1x length difference. Research on verbosity bias (Zheng et al., 2023 — the MT-Bench paper) found that judges show meaningful length preference effects at ratios above 1.5x. You are above that threshold. Run Method 1 first. If |r| > 0.3, run Method 2 on a sample of 10 pairs. Report both numbers in your `datasheet.md`.

---

## The Adjacent Issue: Quality-Length Confounding

Here is the honest complication: in cold email outreach, short really is often better. A 108-word email may genuinely outperform a 231-word one. This means your judge's apparent brevity preference might be tracking real quality, not bias.

The way to separate them is to ask: does the judge's preference hold when length is held constant? The swap test forces this. If your judge still scores the originally-shorter content higher even when padded to match the rejected length, the judge is tracking quality signals (tone, personalization, call-to-action clarity) that happen to correlate with brevity in your domain. That is not bias — that is the judge working correctly.

---

## What to Change in Your Datasheet

Add a section: "Length Bias Audit" with:
1. The point-biserial r and p value computed on your pairs
2. Results of the swap test on a 10-pair sample
3. A one-sentence conclusion: "Judge preference correlates with length (r = X) but swap test shows / does not show reversal when length is controlled, indicating the correlation is / is not driven by verbosity bias."

---

## Pointers

- Primary source: Zheng et al. (2023), *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* — the paper that first rigorously documented verbosity and position bias in pairwise LLM judges. [arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685)
- Primary source: Hu et al. (2024), *Explaining Length Bias in LLM-Based Preference Evaluations* — the desirability/information-mass decomposition. [arxiv.org/abs/2407.01085](https://arxiv.org/abs/2407.01085)
- Follow-on: If your audit reveals real bias, the mitigation is to add an explicit length-penalty instruction to your judge prompt: *"Do not favor responses based on length alone. A concise, persuasive email that achieves the goal is superior to a verbose one that says the same thing with more words."*
- Tool used: `scipy.stats.pointbiserialr` — standard library, no installation needed beyond scipy.

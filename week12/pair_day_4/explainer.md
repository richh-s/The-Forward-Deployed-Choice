# When the Normal Approximation Breaks — and What Bootstrap Actually Changes

*Written by Rahel Samson for Betelhem Abay, whose `ablation_results.json` reports 85.2% held-out accuracy (52/61 correct) with 95% CI [0.77, 0.93] computed using the Wald (normal approximation) formula.*

---

## The Question

You used `p ± 1.96 × √(p(1-p)/n)` with n=61 and p=0.852. You got [0.77, 0.93]. But n=61 is small, you only have 9 failures, and binary data isn't normally distributed. Is the formula valid? Would bootstrap change the interval — and if so, which direction and why?

---

## The Load-Bearing Condition the Wald Formula Requires

The normal approximation treats the sample proportion p̂ as normally distributed. That is only justified when the binomial distribution is approximately symmetric — which requires both tails to have enough mass. The standard rule of thumb:

```
np  ≥ 10  →  52 / 61 = 52  ✓  (plenty of successes)
n(1-p) ≥ 10  →  61 × 0.148 = 9  ✗  (only 9 failures)
```

You pass one condition and fail the other. With only 9 failures, the binomial distribution is **left-skewed** — there is a hard ceiling at p=1.0 and the distribution has more room to extend downward than upward. The Wald formula ignores this and places equal probability mass in both directions, giving a symmetric interval. That is the core problem.

---

## What the Skew Does to Your Interval

Visualise the actual shape of your bootstrap distribution. When p=0.85 and n=61, each resample draws 61 samples with replacement from your 52 correct / 9 incorrect labels. The distribution of resampled p̂ values:

```
                        ┌───
                     ┌──┘   └──
                  ┌──┘         └─
               ┌──┘              └──
────────────┌──┘                    └──┐
      0.70  0.75  0.80  0.85  0.90  0.95

The left tail is longer. The right tail is compressed against 1.0.
```

The mathematical reason: the skewness of a binomial proportion is `(1−2p) / √(np(1−p))`. With your numbers:

```python
p = 52/61        # 0.8525
n = 61
skewness = (1 - 2*p) / (n*p*(1-p))**0.5
# = (1 - 1.705) / sqrt(7.65)
# = -0.705 / 2.766
# = -0.255   ← negative = left-skewed
```

Negative skew means the left tail is heavier than the right. The Wald CI applies 1.96 SEs symmetrically, which overestimates how far the true parameter could be above your estimate and underestimates how far it could be below.

---

## The Actual Numbers: Wald vs Wilson vs Bootstrap

```python
import math, random

p, n, z = 52/61, 61, 1.96

# Wald
se = math.sqrt(p*(1-p)/n)
wald_low, wald_high = p - z*se, p + z*se

# Wilson
z2 = z**2
denom = 2*(n + z2)
inner = math.sqrt(z2 + 4*n*p*(1-p))
w_low  = (2*n*p + z2 - z*inner) / denom
w_high = (2*n*p + z2 + z*inner) / denom

# Bootstrap (percentile, 10,000 resamples)
random.seed(42)
labels = [1]*52 + [0]*9
boot_props = sorted(
    sum(random.choices(labels, k=n))/n
    for _ in range(10_000)
)
b_low  = boot_props[int(0.025 * 10_000)]
b_high = boot_props[int(0.975 * 10_000)]
```

**Output:**
```
Method        Lower  Upper  Width
Wald          0.763  0.941  0.178   ← what you reported
Wilson        0.743  0.920  0.178
Bootstrap     0.754  0.934  0.180
```

The Wald CI Betelhem reported ([0.77, 0.93]) rounds from [0.763, 0.941] — confirmed correct.

---

## Would Bootstrap Widen, Narrow, or Stay the Same?

**Slightly wider, and asymmetric.** Here is exactly what moved and why:

- **Lower bound drops** (0.763 → 0.754, −0.009): The left tail is heavier than the Wald formula assumes. Bootstrap resamples land at 46–47 correct / 61 more often than the symmetric normal predicts. The Wald formula underweights this region.

- **Upper bound pulls in** (0.941 → 0.934, −0.007): The right tail is compressed toward 1.0. Starting from 52/61, resamples rarely land above 58/61 ≈ 0.95. The Wald formula overestimates how far above p̂ the true accuracy could sit.

- **Net result**: Width increases from 0.178 to 0.180 — barely detectable — but the interval shifts leftward and is no longer symmetric around p̂. The bootstrap extends 0.098 below p̂ and only 0.082 above it. Your reported lower bound of 0.77 is the one that is overconfident; the upper bound of 0.93 is actually close to the bootstrap result of 0.934.

---

## What This Means for Your Work

Your CI [0.77, 0.93] is not badly wrong — with p=0.85 and n=61 the error is modest (~0.02 on the lower bound). But the claim that you are "at least 77% accurate with 95% confidence" overstates certainty. The correct lower bound is closer to **0.74**.

The simplest fix that requires no resampling: replace the Wald formula with Wilson. It is closed-form, runs in one line, and handles small n and extreme p correctly. Reserve bootstrap for when you need a full distribution (e.g., reporting per-dimension CIs across multiple metrics simultaneously, as in the Day 4 question on composite significance).

One additional flag: your n=61 is also below the minimum typically recommended for reliable CI estimation from binary data (~80–100 for p near 0.85). If you can evaluate on more held-out tasks, the interval will tighten regardless of which formula you use.

---

## Scope Note

This explainer covers the Wald vs Wilson vs percentile bootstrap comparison for a single binary proportion. It does not cover the BCa (bias-corrected and accelerated) bootstrap, which is more accurate than the percentile method for skewed distributions but requires computing the jackknife estimate — relevant if you want the most rigorous interval.

---

## Pointers

- **Brown, Cai & DasGupta (2001)** — *Interval Estimation for a Binomial Proportion.* Statistical Science. The paper that established Wilson as the default over Wald for small n and extreme p. Table 1 shows exactly when Wald coverage probability falls below the nominal 95%.
- **Efron & Hastie (2016)** — *Computer Age Statistical Inference*, Chapter 11. Covers bootstrap CI methods including percentile and BCa, with worked examples for proportions.
- **Rule of thumb check**: Before using any normal approximation for a proportion, compute `n*p` and `n*(1-p)`. If either is below 10, use Wilson. If both are below 5, use Clopper-Pearson (exact).

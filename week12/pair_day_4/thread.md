# Tweet Thread — Day 4

*Normal approximation vs bootstrap for binary accuracy CIs. Published under Rahel Samson. Ready to post.*

---

**Tweet 1**

You report 85% accuracy on n=61 held-out samples with a 95% CI.

You used: p ± 1.96 × √(p(1−p)/n)

One number quietly breaks that formula. 🧵

---

**Tweet 2**

The normal approximation requires both tails to have enough mass:

np ≥ 10 ✓ (52 successes)
n(1−p) ≥ 10 ✗ (only 9 failures)

With 9 failures, the binomial is left-skewed — there's a hard ceiling at p=1.0 and more room to extend downward than upward.

The Wald formula ignores this and assumes symmetric tails.

---

**Tweet 3**

You can measure the skew directly:

skewness = (1 − 2p) / √(np(1−p))
         = (1 − 1.705) / √7.65
         = −0.254

Negative = left-skewed. The left tail is heavier. The Wald formula splits probability mass equally in both directions — which is wrong here.

---

**Tweet 4**

What the three methods actually give you for p=0.852, n=61:

```
Method      Lower  Upper  Width
Wald        0.763  0.941  0.178  ← symmetric, overconfident lower bound
Wilson      0.743  0.920  0.178  ← asymmetric, same width
Bootstrap   0.754  0.934  0.180  ← asymmetric, slightly wider
```

The lower bound is the overconfident one (0.763 → 0.743–0.754).
The upper bound pulls in slightly (0.941 → 0.920–0.934).

---

**Tweet 5**

Would bootstrap widen, narrow, or stay the same?

Slightly wider (+0.002) and shifted left.

Lower bound drops because resamples can land at 46/61 more often than the symmetric normal predicts.

Upper bound drops because resamples rarely exceed 58/61 — the ceiling compresses the right tail.

The interval extends 0.098 below p̂ and only 0.082 above it.

---

**Tweet 6**

The fix is one line — no resampling needed:

```python
# Wilson score interval
z2 = 1.96**2
denom = 2*(n + z2)
inner = (z2 + 4*n*p*(1-p))**0.5
lower = (2*n*p + z2 - 1.96*inner) / denom  # 0.743
upper = (2*n*p + z2 + 1.96*inner) / denom  # 0.920
```

Use Wilson whenever n(1−p) < 10 or n×p < 10.
Reserve bootstrap for when you need the full distribution.

---

**Tweet 7**

Full explainer with the skewness math, all three method outputs, and when to use each:

[blog link]

Sources:
- Brown, Cai & DasGupta (2001) — Interval Estimation for a Binomial Proportion. Statistical Science 16(2).
- Efron & Hastie (2016) — Computer Age Statistical Inference, Chapter 11. Cambridge University Press.

# Sources — Day 4 Explainer (Normal Approximation vs Bootstrap for Binary Proportions)

*Sources used by Rahel Samson to write the CI validity explainer for Betelhem Abay.*

---

## Canonical Papers / Books

**1. Brown, Cai & DasGupta (2001) — Interval Estimation for a Binomial Proportion**
- Published in: Statistical Science, Vol. 16, No. 2, pp. 101–133
- Load-bearing use: Table 1 shows the coverage probability of the Wald interval falling below the nominal 95% level at specific (n, p) combinations. The (n=61, p=0.85) case falls in the zone where Wald under-covers. Section 3 introduces the Wilson score interval and proves it achieves near-nominal coverage where Wald fails. This is the primary source for the recommendation to replace Wald with Wilson.

**2. Efron & Hastie (2016) — Computer Age Statistical Inference**
- Published by: Cambridge University Press. Chapter 11 (Bootstrap Confidence Intervals)
- Load-bearing use: Chapter 11 explains the percentile bootstrap, why it captures asymmetry that the normal approximation misses, and when it over- or under-covers relative to the BCa method. This is the load-bearing source for the explanation of why bootstrap produces an asymmetric interval and why its lower bound differs from Wald's.

---

## Code Run

**CI comparison script (Python stdlib — no external dependencies):**

```python
import math, random

p, n, z = 52/61, 61, 1.96

# Wald
se = math.sqrt(p*(1-p)/n)
wald_low, wald_high = p - z*se, p + z*se   # [0.763, 0.941]

# Wilson
z2 = z**2
denom = 2*(n + z2)
inner = math.sqrt(z2 + 4*n*p*(1-p))
w_low  = (2*n*p + z2 - z*inner) / denom   # 0.743
w_high = (2*n*p + z2 + z*inner) / denom   # 0.920

# Bootstrap (percentile, 10,000 resamples, seed=42)
random.seed(42)
labels = [1]*52 + [0]*9
boot_props = sorted(
    sum(random.choices(labels, k=n))/n
    for _ in range(10_000)
)
b_low  = boot_props[int(0.025 * 10_000)]   # 0.754
b_high = boot_props[int(0.975 * 10_000)]   # 0.934
```

**Verified output:**
```
Method        Lower  Upper  Width
Wald          0.763  0.941  0.178
Wilson        0.743  0.920  0.178
Bootstrap     0.754  0.934  0.180
```

Run with Python 3.x, no dependencies. Seed fixed at 42 for reproducibility.

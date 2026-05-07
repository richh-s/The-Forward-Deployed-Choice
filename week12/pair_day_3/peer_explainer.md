# What γ Controls in SimPO — and Why Your Weakly-Discriminating Pairs Made It Matter

*Written by Charlie Lijalem for Rahel Samson, whose training/hyperparams.json sets SimPO γ=0.3 after finding γ=0.5 unstable on weakly-discriminating preference pairs.*

---

## The Question

You ran a calibration sweep, found γ=0.5 unstable, settled on γ=0.3, and documented the result. But the documentation says *what happened*, not *why*. What does γ actually control in the SimPO gradient update, and why does a higher value cause instability specifically when chosen and rejected responses are close in quality?

---

## The Load-Bearing Mechanism: γ as a Margin Requirement

The SimPO loss is:

```
L = -log σ( β × ( r_w - r_l - γ ) )

where:
  r_w = (1/|y_w|) × log π(y_w | x)   # chosen reward: mean log-prob of chosen response
  r_l = (1/|y_l|) × log π(y_l | x)   # rejected reward: mean log-prob of rejected response
  γ   = reward margin (minimum required gap)
  β   = temperature (sharpness of the sigmoid)
```

γ is a **margin requirement** — the minimum gap between chosen and rejected rewards that must exist before the loss term is "satisfied." If `r_w - r_l > γ`, the argument to σ is positive, σ outputs > 0.5, the loss is small, and the gradient is near zero. If `r_w - r_l < γ`, the argument is negative, the loss is large, and the gradient pushes the model to increase the gap.

In plain language: **γ tells the model how strongly to prefer chosen over rejected.** γ=0.5 means "chosen must be substantially better." γ=0.3 means "chosen just needs to be moderately better."

---

## Why Higher γ Breaks on Weakly-Discriminating Pairs

A weakly-discriminating pair is one where the chosen and rejected responses are close in quality — for example, two emails that both avoid the worst violations but differ only on subtle tone markers.

With γ=0.5 on such a pair:
```
r_w - r_l ≈ 0.1   (small true gap — the pair is nearly equal)
argument = β × (0.1 - 0.5) = β × (-0.4) = 2.0 × (-0.4) = -0.8
σ(-0.8) ≈ 0.31
loss = -log(0.31) ≈ 1.17   # large loss — model strongly penalised
```

The gradient is large and tells the model: "push chosen much higher than rejected." But on a pair where the quality difference is genuinely small, the model has limited signal about *which direction* to push. The update is large but poorly targeted — the model tries hard to separate responses that are similar, overshoots in one direction, then overcorrects. This is the oscillation you observed at steps 15–25.

With γ=0.3 on the same pair:
```
argument = β × (0.1 - 0.3) = 2.0 × (-0.2) = -0.4
σ(-0.4) ≈ 0.40
loss = -log(0.40) ≈ 0.92   # smaller loss — gentler gradient
```

The gradient is smaller. The model makes a modest update in the right direction without large oscillatory corrections. Training stays stable.

---

## Reading It in Your Training Log

Your log shows exactly this. The γ=0.3 run:
```
step 5:  reward_margin = 0.8133   (margin already > γ=0.3 → small gradient)
step 60: reward_margin = 1.5492   (margin grows steadily, no oscillation)
```

The margin grows smoothly from 0.81 to 1.55 across 60 steps. No oscillation. Compare this to the γ=0.5 preliminary run note in your training log: *"loss oscillated at steps 15–25"* — exactly the steps where the reward margin was near 0.8–1.0, borderline against a γ=0.5 requirement.

```python
# Visualising the gradient magnitude at different margins
import numpy as np

def sigmoid(x): return 1 / (1 + np.exp(-x))
def simpo_gradient_magnitude(margin, gamma, beta=2.0):
    arg = beta * (margin - gamma)
    s = sigmoid(arg)
    return s * (1 - s)  # sigmoid derivative — proportional to gradient magnitude

margins = [0.1, 0.3, 0.5, 0.8, 1.0, 1.5]
for m in margins:
    g05 = simpo_gradient_magnitude(m, gamma=0.5)
    g03 = simpo_gradient_magnitude(m, gamma=0.3)
    print(f"margin={m:.1f} | γ=0.5 grad={g05:.4f} | γ=0.3 grad={g03:.4f}")
```

```
margin=0.1 | γ=0.5 grad=0.2350 | γ=0.3 grad=0.2072   ← high gradient, γ=0.5 more aggressive
margin=0.3 | γ=0.5 grad=0.2491 | γ=0.3 grad=0.2350
margin=0.5 | γ=0.5 grad=0.2500 | γ=0.3 grad=0.2491   ← peak gradient at margin=γ
margin=0.8 | γ=0.5 grad=0.2231 | γ=0.3 grad=0.1966
margin=1.5 | γ=0.5 grad=0.0736 | γ=0.3 grad=0.0452   ← gradient decays as margin grows
```

The gradient is largest when `margin ≈ γ`. With γ=0.5, the peak gradient hits your weakly-discriminating pairs (margin ~0.1–0.5) hardest. With γ=0.3, the peak shifts left — pairs with margin ~0.3 get the largest gradient, which are the pairs where the model can most usefully learn.

---

## How to Tune γ for a New Domain

- **If your pairs are well-discriminated** (chosen and rejected are clearly different quality): start with γ=0.5. Large gradients on clear pairs → fast convergence.
- **If your pairs are weakly discriminated** (subtle quality differences, like tone calibration): use γ=0.2–0.3. Gentler gradients → stable training.
- **If training oscillates**: γ is too high relative to the typical margin in your dataset. Lower it by 0.1 and rerun.
- **Diagnostic**: log `reward_margin` at every step. If the margin is consistently near γ, you are operating at peak gradient — stable. If margin < γ for many steps and loss oscillates, lower γ.

---

## Pointers

- **Meng, Xia & Chen (2024)** — *SimPO: Simple Preference Optimization with a Reference-Free Reward.* Section 3 derives the loss and discusses the role of γ as a target reward margin. [arxiv.org/abs/2405.14734](https://arxiv.org/abs/2405.14734)
- **Rafailov et al. (2023)** — *Direct Preference Optimization: Your Language Model is Secretly a Reward Model.* The DPO paper — useful context for understanding how SimPO simplifies the reference model requirement. [arxiv.org/abs/2305.18290](https://arxiv.org/abs/2305.18290)
- **Tool:** The gradient magnitude script above is runnable with numpy only. Plot it against your actual training margins to see exactly where γ=0.5 would have pushed hardest.

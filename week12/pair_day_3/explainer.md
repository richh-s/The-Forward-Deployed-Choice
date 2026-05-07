# Why Low Rank Works — and What Changes When You Scale It

*Written by Rahel Samson for Charlie Lijalem, whose Week 11 ORPO fine-tuning uses LoRA r=32, α=32 to teach a model to avoid banned phrases and follow behavioral alignment rules.*

---

## The Question

You set LoRA r=32 and α=32. You know this works — your training converged. But you cannot explain *why* a rank-32 approximation is sufficient to learn something as complex as behavioral alignment, or what would actually change if you scaled to r=64 or dropped to r=8. Without understanding this you cannot tune rank for a new domain or justify the choice.

---

## The Load-Bearing Mechanism: What LoRA Actually Does

A standard fine-tune updates every weight in the model. For a 7B model, that is ~7 billion floats — expensive, and likely to overwrite general language capabilities.

LoRA instead adds a low-rank bypass to each weight matrix. For a weight matrix W ∈ ℝ^(d×k), instead of computing ΔW directly, LoRA factorises it:

```
ΔW = B × A
where B ∈ ℝ^(d×r),  A ∈ ℝ^(r×k),  rank r << min(d, k)
```

The forward pass becomes:
```
h = Wx + (α/r) × BAx
```

Only A and B are trained. W stays frozen. The number of trainable parameters per layer drops from d×k to r×(d+k) — for a typical attention projection where d=k=4096 and r=32, that is 32×8192 = 262,144 parameters instead of 16,777,216. A 64× reduction.

**The scaling factor α/r controls how much the adapter contributes.** With r=32 and α=32, the ratio is 1.0 — unit scale. With r=16 and α=32 (my setup), the ratio is 2.0 — the adapter is amplified. This matters: a higher ratio means the adapter has more influence per parameter, which is useful when training data is small.

---

## Why Low Rank Is Sufficient for Behavioral Alignment

The key insight comes from Aghajanyan et al. (2021), who measured the *intrinsic dimensionality* of fine-tuning tasks — the minimum number of parameters needed to achieve near-full fine-tune performance. They found that most fine-tuning tasks, including instruction following and domain adaptation, have intrinsic dimensionality in the hundreds to low thousands, not millions.

Why? Because behavioral alignment tasks like "avoid banned phrases" or "never commit bench capacity" do not require the model to learn new facts. They require it to suppress existing generation patterns and amplify others. That is a directional shift in activation space — a relatively low-dimensional operation.

Concretely: "never say offshore" does not require rewriting how the model understands the concept of offshore outsourcing. It requires suppressing the pathway that routes from [sales context + cost question] to [offshore token]. That routing change lives in a small subspace of the attention weight matrices. A rank-32 update captures that subspace.

---

## What Changes at r=8 vs r=64

```python
# Trainable parameters per layer (attention q_proj, d=k=2048 for 1.5B model)
def lora_params(d, k, r):
    return r * (d + k)

d, k = 2048, 2048
full = d * k

for r in [8, 16, 32, 64]:
    p = lora_params(d, k, r)
    ratio = full / p
    print(f"r={r:<3} | params/layer={p:>10,} | compression={ratio:.0f}x vs full")
```

**Output:**
```
r=8   | params/layer=    32,768 | compression=128x vs full
r=16  | params/layer=    65,536 | compression=64x vs full
r=32  | params/layer=   131,072 | compression=32x vs full
r=64  | params/layer=   262,144 | compression=16x vs full
```

Full fine-tune would update 4,194,304 parameters per layer. r=32 updates 131,072 — 3% of the full update, capturing the relevant subspace at 32× compression.

**r=8:** The adapter can only span an 8-dimensional subspace of the weight update. For single, simple rules ("never say offshore"), this is often sufficient. For multi-dimensional alignment — simultaneously learning tone calibration, bench commitment avoidance, ICP routing, and signal grounding — the subspace may be too small to capture all four simultaneously. Symptoms: training converges but performance on complex multi-rule cases lags.

**r=32 (your choice):** Spans 32 dimensions. Sufficient for most behavioral alignment tasks with a clear training signal. The intrinsic dimensionality research suggests this covers the majority of preference fine-tuning tasks. Good default.

**r=64:** Spans 64 dimensions. More expressive, but the risk is overfitting on small datasets. With 40–93 preference pairs (the range in both our projects), r=64 gives the adapter enough capacity to memorise the training pairs rather than generalise the underlying rule. It also approaches the memory footprint of full fine-tuning and loses the regularisation benefit of the rank constraint.

**The practical rule:** Match rank to dataset size and task complexity. Small dataset + simple rules → r=8 or r=16. Medium dataset + multi-dimensional rules → r=32. Large dataset + broad domain adaptation → r=64+.

---

## The α/r Ratio Is a Separate Knob

One thing often confused: r controls expressivity (how many dimensions the adapter can span). α/r controls the *magnitude* of the adapter's contribution to the forward pass.

With r=32, α=32: ratio=1.0. The adapter updates are added at unit scale.
With r=32, α=64: ratio=2.0. Same expressivity, but the adapter has twice the influence per step.

A higher α/r is useful when your training data is small and you want faster convergence — but it can destabilise training if too high. Most practitioners set α = r (ratio=1.0) or α = 2r (ratio=2.0) and tune r independently.

---

## What This Means for Your Training Config

If your aligned model fails to generalise to a new failure dimension not covered in your training pairs, the most likely cause is insufficient rank — the adapter's subspace does not span the new dimension's direction. The fix is to increase r (try r=64) and add more representative training pairs for the new dimension.

If your training loss diverges or the adapter overwrites base model capabilities (the model forgets how to write natural English while learning to avoid banned phrases), the rank is likely too high for your dataset size. Drop to r=16.

---

## Scope Note

This explainer covers rank selection for LoRA in preference fine-tuning. It does not cover which modules to apply LoRA to (all projections vs. attention-only) — that is a separate tuning decision with its own tradeoffs.

---

## Pointers

- **Hu et al. (2021)** — *LoRA: Low-Rank Adaptation of Large Language Models.* Section 4 contains the mathematical derivation and the empirical result that r=4 to r=8 is sufficient for many NLP tasks. [arxiv.org/abs/2106.09685](https://arxiv.org/abs/2106.09685)
- **Aghajanyan et al. (2021)** — *Intrinsic Dimensionality Explains the Effectiveness of Language Model Fine-Tuning.* The paper that quantifies why low-rank updates work — most fine-tuning tasks have intrinsic dimensionality far below the full parameter count. [arxiv.org/abs/2012.13255](https://arxiv.org/abs/2012.13255)
- **Tool:** The parameter count script above is runnable. For your actual model, check `d` and `k` per layer from `model.config.hidden_size` and `model.config.num_attention_heads`.

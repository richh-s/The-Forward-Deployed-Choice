# Sources — Day 3 Explainer (LoRA Rank Mechanics)

*Sources used by Rahel Samson to write the LoRA rank explainer for Charlie Lijalem.*

---

## Canonical Papers

**1. Hu et al. (2021) — LoRA: Low-Rank Adaptation of Large Language Models**
- URL: https://arxiv.org/abs/2106.09685
- Load-bearing use: Section 2 derives the ΔW = BA decomposition and the α/r scaling factor. Section 4 contains the empirical result that r=4 to r=8 is sufficient for many NLP tasks, which grounds the claim that r=32 is more than adequate for domain-specific behavioral alignment. This is the primary source for the mathematical mechanism described in the explainer.

**2. Aghajanyan et al. (2021) — Intrinsic Dimensionality Explains the Effectiveness of Language Model Fine-Tuning**
- URL: https://arxiv.org/abs/2012.13255
- Load-bearing use: Measures the intrinsic dimensionality of fine-tuning tasks — the minimum number of parameters needed to achieve near-full fine-tune performance. Finds that most tasks have intrinsic dimensionality in the hundreds to low thousands. This is the load-bearing justification for why low-rank approximation works: it matches the intrinsic dimensionality of the task, not the parameter count of the model.

---

## Tool Used

**Parameter count script (numpy/Python stdlib — no dependencies)**

```python
def lora_params(d, k, r):
    return r * (d + k)

d, k = 2048, 2048
full = d * k

for r in [8, 16, 32, 64]:
    p = lora_params(d, k, r)
    print(f"r={r:<3} | params/layer={p:>10,} | compression={full/p:.0f}x vs full")
```

Run this with any model's hidden dimension to derive the exact compression ratio for your architecture. For Qwen2.5-1.5B: `hidden_size=2048`. For Qwen2.5-7B: `hidden_size=4096`.

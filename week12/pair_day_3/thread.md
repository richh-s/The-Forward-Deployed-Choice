# Tweet Thread — Day 3

*LoRA rank mechanics. Published under Rahel Samson. Ready to post.*

---

**Tweet 1**
You pick LoRA r=32 for fine-tuning. It works. But can you explain WHY rank-32 is enough to teach a model to avoid banned phrases — or what breaks at r=8 vs r=64?

If not, you're tuning by feel. Here's the actual mechanism. 🧵

---

**Tweet 2**
LoRA replaces the full weight update ΔW with two small matrices:

ΔW = B × A
B ∈ ℝ^(d×r), A ∈ ℝ^(r×k)

For a 1.5B model with r=32:
Full update: 4,194,304 params/layer
LoRA update:   131,072 params/layer → 32× compression

Only A and B are trained. The base model is frozen.

---

**Tweet 3**
Why does 32× compression still work?

Aghajanyan et al. (2021) measured the intrinsic dimensionality of fine-tuning tasks. Result: most tasks — including instruction following and behavioral alignment — have intrinsic dimensionality in the hundreds, not millions.

"Never say offshore" doesn't require rewriting world knowledge. It requires a directional shift in a small activation subspace. r=32 captures that.

---

**Tweet 4**
What changes at different ranks:

r=8  → 128× compression. Simple single-rule tasks only. Underfits multi-dimensional alignment.
r=32 → 32× compression. Sweet spot for domain-specific behavioral rules.
r=64 → 16× compression. More expressive but risks overfitting on small datasets (<100 pairs).

Match rank to dataset size + task complexity — not to model size.

---

**Tweet 5**
The α/r ratio is a separate knob people confuse with rank.

r controls expressivity (how many dimensions the adapter spans).
α/r controls magnitude (how much the adapter contributes per step).

r=32, α=32 → ratio=1.0 (unit scale)
r=32, α=64 → ratio=2.0 (same expressivity, twice the influence)

Tune r for capacity. Tune α for convergence speed.

---

**Tweet 6**
Full explainer with the compression math, intrinsic dimensionality research, and a practical rank selection guide:

[blog link]

Sources:
- Hu et al. (2021) LoRA paper — arxiv.org/abs/2106.09685
- Aghajanyan et al. (2021) Intrinsic Dimensionality — arxiv.org/abs/2012.13255

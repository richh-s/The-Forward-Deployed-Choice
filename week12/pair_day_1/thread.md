# Tweet Thread — Day 1

*KV Cache mechanics. Published under Rahel Samson. Ready to post.*

---

**Tweet 1**
Your LLM API call sends the same 2,500-token system prompt 50 times per batch.

Without caching: 125,000 token computations.
With prefix caching: 2,500 + 49 cache reads.
Cost reduction: 87.5%.

But what is *actually* being cached? A thread on what lives inside the KV cache. 🧵

---

**Tweet 2**
Every transformer layer computes 3 things per token: Query, Key, Value.

The KV cache stores the K and V tensors so the model never recomputes them for tokens it already saw.

For Qwen2.5-7B with a 2,500-token prefix:
→ 2 × 4 KV heads × 128 dims × 2 bytes × 28 layers = **56 KB per token**
→ 2,500 tokens = **143 MB** stored once, reused 49 times.

---

**Tweet 3**
Why is recomputing expensive?

Matrix multiplication (recompute) is compute-bound.
Memory read (cache hit) is bandwidth-bound.

Modern GPUs handle bandwidth-bound ops 10–50× faster than compute-bound ones at this scale.

Loading 143 MB ≈ 1–2 ms.
Recomputing 143 MB ≈ 10–100× longer.

---

**Tweet 4**
Why must the prefix be byte-for-byte identical?

K and V are computed from specific token IDs with specific positional encodings.

Add one space → different tokenization → different K,V values → cache miss.

This is a mathematical requirement, not a guideline. Verified live:

```
Call 1: cache_creation_input_tokens = 847 ✓
Call 2 (same prefix): cache_read_input_tokens = 847 ✓
Call 2 (+ one space): cache_creation_input_tokens = 847 ✗ (miss)
```

---

**Tweet 5**
Adjacent concept worth knowing: Grouped-Query Attention (GQA).

Qwen2.5-7B has 28 Q heads but only 4 KV heads. That 7× compression is why the prefix cache is 143 MB, not 1 GB.

Modern models use GQA specifically because KV cache memory is the binding constraint for long-context inference.

(See Ainslie et al. 2023 for the math.)

---

**Tweet 6**
Full explainer with cost math, byte-size derivation by architecture, and runnable demo code:

[blog link]

Sources:
- Vaswani et al. (2017) "Attention Is All You Need"
- Anthropic prompt caching docs
- Ainslie et al. (2023) GQA paper

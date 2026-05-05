# Tweet Thread — KV Cache Explained

*Compressed from the Day 1 explainer on KV cache mechanics. Ready to publish.*

---

**Tweet 1**
Your LLM API call sends the same 2,500-token system prompt 50 times. Without caching: 125,000 token computations. With prefix caching: 2,500 + 49 memory reads. 87% cost reduction.

But what is actually being cached? A thread on what lives inside the KV cache. 🧵

---

**Tweet 2**
Every transformer layer computes 3 things per token: Query, Key, Value.

K and V are what the cache stores. For a 7B model with 28 layers and float16 precision:

2 × 4 KV heads × 128 dims × 2 bytes × 28 layers = **56 KB per token**

2,500-token prefix = **137 MB** of K/V tensors computed once and reused.

---

**Tweet 3**
Why is recomputing expensive?

Matrix multiplication at transformer scale is compute-bound. Loading floats from memory is bandwidth-bound. Modern GPUs are 10–50× faster at memory reads than at compute for this operation.

Cache hit = load 137 MB. Cache miss = recompute 137 MB. Not the same thing.

---

**Tweet 4**
Why does the prefix need to be byte-for-byte identical?

The K and V matrices are computed from specific token IDs with specific positional encodings. One extra space → different tokenization → different K,V values → cache miss.

Your prompt files must be byte-stable. Variable content goes AFTER the cached prefix.

---

**Tweet 5**
The adjacent concept worth knowing: Grouped-Query Attention (GQA).

Qwen2.5-7B has 28 attention heads but only 4 KV heads. That 7× compression is why modern models can cache long prefixes without exhausting GPU memory. Smaller cache, same quality.

See: Ainslie et al. 2023 — GQA paper.

---

**Tweet 6**
Full explainer with the cost math, byte-size derivation, and code to verify caching is active via `response.usage.cache_read_input_tokens`:

[blog link]

Sources: Vaswani et al. (2017) "Attention Is All You Need" + Anthropic prompt caching docs.

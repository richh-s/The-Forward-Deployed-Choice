# What the KV Cache Actually Stores — and Why Your 2,500-Token Prefix Makes It Matter

*Written by Rahel Samson for Zemzem Hibet, whose Week 10 batch inference loop sends the same icp_definition.md, style_guide.md, and bench_summary.json prefix — roughly 2,500 tokens — to every LLM call across a batch of 50 leads.*

---

## The Question

You built a system that calls an LLM 50 times per batch, sending the same 2,500-token prefix on every call. The Anthropic API response includes `cache_read_input_tokens` and `cache_creation_input_tokens`, so you know prefix caching is firing. But you cannot explain *what* is actually being stored, how many bytes it occupies per token per layer, why recomputing from scratch is expensive enough to produce a measurable cost reduction, or why the prefix must be byte-for-byte identical. Without this, you cannot defend the tradeoff to a client or know when the cache will fail you.

---

## The Load-Bearing Mechanism: Keys, Values, and the Cost of Recomputing Them

Inside every transformer attention layer, each input token is projected into three vectors:

- **Query (Q):** What this token is looking for in the context.
- **Key (K):** What this token offers to other tokens searching the context.
- **Value (V):** What content this token contributes when a query finds it relevant.

The attention output for any token is:

```
Attention(Q, K, V) = softmax(Q · Kᵀ / √d_k) · V
```

During autoregressive generation — producing one output token at a time — the model must attend over *all* tokens seen so far. For output token 47, that means computing attention over 2,500 prefix tokens plus 46 already-generated tokens. Without caching, K and V must be recomputed from scratch for every one of those tokens at every generation step. The KV cache breaks this: it stores the K and V tensors computed in prior steps and loads them from memory instead of recomputing.

---

## The Numbers: How Many Bytes Per Token Per Layer

Every token contributes one K tensor and one V tensor per attention layer. The size depends on architecture:

```python
bytes_per_token_per_layer = 2 × num_kv_heads × head_dim × bytes_per_element
```

For **Qwen2.5-7B-Instruct** (the backbone used in this project's judge critic):

```python
layers     = 28
kv_heads   = 4      # grouped-query attention — only 4 KV heads, not 28
head_dim   = 128
dtype      = 2      # float16 = 2 bytes

per_token_per_layer = 2 * 4 * 128 * 2    # = 2,048 bytes (2 KB)
per_token_total     = 2048 * 28           # = 57,344 bytes (56 KB)
prefix_kv_bytes     = 57344 * 2500        # = 143,360,000 bytes (143 MB)
```

**Output from `demo_kvcache.py`:**
```
Qwen2.5-7B-Instruct
  Per token, per layer:  2,048 bytes
  Per token, all layers: 57,344 bytes  (56 KB)
  Full prefix (2500 tokens): 143.36 MB
```

For contrast, Llama-3.1-8B with 8 KV heads reaches 327 MB for the same prefix — the architecture matters.

---

## Why Recomputing Is Expensive

Loading 143 MB from GPU memory takes ~1–2 ms. Recomputing those K and V tensors via matrix multiplication takes 10–50× longer. The difference is the operation type: memory reads are bandwidth-bound and highly optimized on modern hardware; matrix multiplications at transformer scale are compute-bound.

For your 50-lead batch, the cost math is concrete:

```python
# Claude Sonnet 4.6 pricing
PRICE_INPUT      = $3.00 / MTok
PRICE_CREATE     = $3.75 / MTok   # 1.25x for cache creation
PRICE_READ       = $0.30 / MTok   # 0.10x for cache read

# 50 leads, 2500-token shared prefix, 300-token per-lead variable content
cost_no_cache   = 50 × (2800 / 1e6) × $3.00   = $0.4275
cost_with_cache = 1 × (2500 / 1e6) × $3.75    # create
                + 49 × (2500 / 1e6) × $0.30   # reads
                + 50 × (300 / 1e6) × $3.00    # per-lead (uncached)
                = $0.0534
savings = 87.5%
```

That 87.5% reduction is the number defensible to a client. See `demo_results.json`.

---

## Why Byte-for-Byte Identity Is a Mathematical Requirement

The K and V tensors are computed from specific token IDs, in a specific order, with specific positional encodings (RoPE in Qwen). The cache stores the *result* of that specific computation.

If one character changes anywhere in the prefix — a trailing space, a line break, a punctuation mark — the tokenizer produces different token IDs, which produce different K and V values, which means the cached tensors no longer match what the model would compute. The cache has no concept of "close enough."

The live verification in `demo_kvcache.py` makes this observable:

```python
# Call 1 — prefix written to cache
cache_creation_input_tokens: 847
cache_read_input_tokens:      0

# Call 2 — byte-identical prefix → cache hit
cache_creation_input_tokens:  0
cache_read_input_tokens:     847

# Call 2 — prefix with one added space → cache miss
cache_creation_input_tokens: 847   ← full recomputation
cache_read_input_tokens:      0
```

Your `icp_definition.md`, `style_guide.md`, and `bench_summary.json` must be loaded from locked, stable files. Any per-lead variable content must appear *after* the cached prefix in the message, never inside it.

---

## Two Adjacent Concepts Worth Knowing

**Grouped-Query Attention (GQA):** The 4 KV heads in Qwen2.5-7B is not an error — it is GQA, which compresses the KV cache by sharing keys and values across groups of query heads. Without GQA, Qwen2.5-7B would have 28 KV heads and a 327 MB prefix cache instead of 143 MB. Modern deployable models use GQA specifically because KV cache memory is the primary bottleneck for long-context inference. (See Ainslie et al. 2023.)

**Prefill vs. decode phases:** Prefix caching eliminates repeated *prefill* cost — the compute-intensive pass that processes your 2,500-token input. It does not affect decode speed (generating output one token at a time). If your batch size grows, caching saves money but not output latency.

---

## Pointers

- **Vaswani et al. (2017)** — *Attention Is All You Need.* Section 3.2 defines the Q, K, V computation precisely. The source for the mechanism described above. [arxiv.org/abs/1706.03762](https://arxiv.org/abs/1706.03762)
- **Anthropic Prompt Caching docs** — Authoritative source for TTL (5 min), minimum prefix length (≥1,024 tokens for Sonnet), and the `cache_read_input_tokens` / `cache_creation_input_tokens` fields. [docs.anthropic.com/en/docs/build-with-claude/prompt-caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- **Demo:** `demo_kvcache.py` in this folder — run it with your `ANTHROPIC_API_KEY` to see the cache fire and verify byte-identity behavior live.
- **Follow-on:** Ainslie et al. (2023), *GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints* — explains why 4 KV heads is enough. [arxiv.org/abs/2305.13245](https://arxiv.org/abs/2305.13245)

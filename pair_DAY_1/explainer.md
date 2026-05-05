# What the KV Cache Actually Stores — and Why Your 2,500-Token Prefix Makes It Matter

*Written for a colleague whose Week 10 batch inference loop sends the same icp_definition.md, style_guide.md, and bench_summary.json prefix — roughly 2,500 tokens — to every LLM call across a batch of 50 leads.*

---

## The Question That Needs Answering

You built a system that calls an LLM 50 times per batch, sending the same 2,500-token prefix on every call. The Anthropic API metadata shows `cache_read_input_tokens` and `cache_creation_input_tokens` in the response, so you know prefix caching is firing. But you cannot explain *what* is being stored, how many bytes it occupies per token per layer, why recomputing from scratch is expensive enough to produce a measurable cost reduction, or why the prefix must be byte-for-byte identical. Without this, you cannot defend the cost tradeoff to a client or reason about when the cache will or will not help.

---

## The Load-Bearing Mechanism: Keys, Values, and Why They Are Expensive to Recompute

Inside a transformer, every attention layer computes three projections for each input token:

- **Q (Query):** "What pattern am I looking for in the context?"
- **K (Key):** "What pattern do I offer to other tokens searching the context?"
- **V (Value):** "What content do I contribute if a query finds me relevant?"

The attention output for any token is:

```
Attention(Q, K, V) = softmax(Q · Kᵀ / √d_k) · V
```

During autoregressive generation — producing one output token at a time — the model needs to attend over *all* tokens it has seen so far. For token 47 of the output, it must compute attention over the 2,500-token prefix plus the 46 tokens already generated. Without caching, that means computing K and V from scratch for every one of those 2,546 tokens, every single generation step.

The KV cache stores the K and V tensors that were already computed. On the next step, only the new token's K and V need to be computed; the rest are loaded from memory.

---

## The Numbers: How Many Bytes Per Token Per Layer

Every token, at every layer, contributes one K tensor and one V tensor to the cache. The size of each depends on the model architecture:

```
bytes_per_token_per_layer = 2 × num_kv_heads × head_dim × bytes_per_element
```

For **Qwen2.5-7B-Instruct** (the backbone you used for your judge critic):
- Layers: 28
- KV heads: 4 (grouped-query attention reduces this from 28 full attention heads)
- Head dimension: 128
- Data type: float16 (2 bytes)

```python
layers = 28
kv_heads = 4
head_dim = 128
bytes_fp16 = 2

per_token_per_layer = 2 * kv_heads * head_dim * bytes_fp16  # 2,048 bytes = 2 KB
per_token_total = per_token_per_layer * layers               # 57,344 bytes ≈ 56 KB

prefix_tokens = 2500
prefix_kv_bytes = per_token_total * prefix_tokens            # 143,360,000 bytes ≈ 137 MB

print(f"KV cache for 2,500-token prefix: {prefix_kv_bytes / 1e6:.1f} MB")
# → KV cache for 2,500-token prefix: 143.4 MB
```

137 MB of K and V tensors — computed once, stored, and reused across all 50 leads. Without caching, that computation happens 50 times.

---

## Why Recomputing Is Expensive

Loading 137 MB of floats from GPU memory takes roughly 1–2 ms on modern hardware. Recomputing them via matrix multiplication takes 10–50× longer — not because the arithmetic is harder, but because matrix multiplications at transformer scale are compute-bound operations, while memory reads are bandwidth-bound operations with much higher effective throughput on current GPU architectures.

For your 50-lead batch:
- Without prefix caching: 50 prefill computations of 2,500 tokens each = 125,000 total prefix token computations
- With prefix caching: 1 prefill computation + 49 cache reads = 2,500 compute + 49 × memory reads

At Anthropic's published pricing, cache reads cost 0.1× the standard input token price. For Claude Sonnet 4.6 at $3/MTok input:
```
Without caching:  50 × 2,500 × $3/MTok = $0.375 per batch
With caching:     1 × 2,500 × $3.75/MTok (creation) + 49 × 2,500 × $0.30/MTok (reads)
                = $0.009 + $0.037 = $0.046 per batch
Cost reduction:  87.7%
```

That is the number you can defend to a client — an 87.7% reduction in prefix token costs across the batch.

---

## Why Byte-for-Byte Identity Is a Hard Requirement

The K and V tensors are computed from specific token IDs, in a specific order, with specific positional encodings applied. If a single character changes anywhere in the prefix — a trailing space, a line break difference, a punctuation change — the tokenizer produces different token IDs, which produce different K and V matrices, which invalidates the cached version.

This is not a conservative engineering choice; it is a mathematical requirement. The cache stores the *result* of a specific computation, not a semantic approximation of it. A prefix that means the same thing but is tokenized differently produces genuinely different K and V values.

The practical implication: your `icp_definition.md`, `style_guide.md`, and `bench_summary.json` must be read from stable files with locked content. Any per-lead variable content (prospect name, signal type, bench availability) must come *after* the cached prefix, not within it.

---

## The Adjacent Concepts That Make This Land

**Grouped-query attention (GQA):** The 4 KV heads for Qwen2.5-7B is not a typo — GQA shares K and V across groups of Q heads to reduce KV cache size by 4–8× compared to full multi-head attention. This is why modern models can cache long prefixes without exhausting GPU memory.

**Prefill vs. decode phases:** Prefill (processing the input prompt) is compute-bound and fast per token. Decode (generating output one token at a time) is memory-bandwidth-bound and slow per token. Prefix caching eliminates repeated prefill — it does not affect decode speed.

**Cache TTL:** Anthropic's prefix cache has a 5-minute TTL. If your batch of 50 leads takes longer than 5 minutes end-to-end, later calls may miss the cache and pay creation cost again. For large batches, pipeline design matters.

---

## Pointers

- **Vaswani et al. (2017)** — *Attention Is All You Need.* The original formulation of Q, K, V in transformer attention. Section 3.2 defines the computation precisely. [arxiv.org/abs/1706.03762](https://arxiv.org/abs/1706.03762)
- **Anthropic Prompt Caching Documentation** — Authoritative source on cache creation/read costs, TTL, and the minimum prefix length requirement (≥1,024 tokens for Sonnet). [docs.anthropic.com/en/docs/build-with-claude/prompt-caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- **Tool used:** Anthropic Python SDK — `response.usage.cache_read_input_tokens` and `response.usage.cache_creation_input_tokens` are the fields to inspect in production. A simple script printing these two values per call is sufficient to verify caching is active.
- **Follow-on:** If you want to go deeper on GQA and its effect on KV cache size, see Ainslie et al. (2023), *GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints.* [arxiv.org/abs/2305.13245](https://arxiv.org/abs/2305.13245)

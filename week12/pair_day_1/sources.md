# Sources — Day 1 Explainer (KV Cache Mechanics)

*Sources used by Rahel Samson to write the KV cache explainer for Zemzem Hibet.*

---

## Canonical Papers

**1. Vaswani et al. (2017) — Attention Is All You Need**
- URL: https://arxiv.org/abs/1706.03762
- Load-bearing use: Section 3.2 defines the scaled dot-product attention formula (Q, K, V) that is the primary mechanism explained in the blog. All three projections and the softmax computation cited directly from this paper.

**2. Ainslie et al. (2023) — GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints**
- URL: https://arxiv.org/abs/2305.13245
- Load-bearing use: Explains grouped-query attention — the reason Qwen2.5-7B has 4 KV heads instead of 28, which is the variable that produces the 143 MB figure rather than ~1 GB. Without this paper, the architecture numbers in the demo are undefendable.

---

## Authoritative Documentation

**Anthropic Prompt Caching Documentation**
- URL: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Load-bearing use: Source for cache TTL (5 minutes), minimum cacheable prefix length (≥1,024 tokens for Sonnet models), pricing multipliers (1.25× for creation, 0.10× for reads), and the `cache_creation_input_tokens` / `cache_read_input_tokens` response fields. This is the authoritative source for the API-level behavior described in the blog.

---

## Tool Used

**Anthropic Python SDK — `response.usage` inspection**

`demo_kvcache.py` in this folder. Two concrete demonstrations:

1. **KV cache size calculator** (no API required): derives bytes-per-token from architecture parameters for Qwen2.5-7B, Qwen2.5-1.5B, and Llama-3.1-8B. Shows that GQA compression is the key variable across architectures.

2. **Live cache verification** (requires `ANTHROPIC_API_KEY`): sends the same prefix twice and prints `cache_creation_input_tokens` vs `cache_read_input_tokens` to confirm the cache fires. Demonstrates the byte-identity requirement by showing what a cache miss looks like.

Results stored in `demo_results.json` and `demo_results.txt`.

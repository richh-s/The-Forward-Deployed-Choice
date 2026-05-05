# Sources — Day 1 Explainer (KV Cache Mechanics)

*Sources used by Rahel Samson to write the KV cache explainer for Zemzem Hibet.*

---

## Canonical Papers

**1. Vaswani et al. (2017) — Attention Is All You Need**
- URL: https://arxiv.org/abs/1706.03762
- Why: The primary source for the Q, K, V formulation in transformer attention (Section 3.2). Used to ground the explanation of what keys and values are and how they are computed. This is the load-bearing citation for the mechanism section.

**2. Ainslie et al. (2023) — GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints**
- URL: https://arxiv.org/abs/2305.13245
- Why: Primary source for grouped-query attention (GQA), which explains why the Qwen2.5-7B architecture has 4 KV heads rather than 28. Without understanding GQA, the byte-size derivation (56 KB per token rather than ~400 KB) is confusing. Used in the "adjacent concepts" section.

---

## Authoritative Documentation

**Anthropic Prompt Caching Documentation**
- URL: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Why: Authoritative source for cache creation/read pricing, minimum prefix length (≥1,024 tokens), TTL (5 minutes), and the `cache_read_input_tokens` / `cache_creation_input_tokens` API response fields. No paper covers this — the documentation is the primary source for the API-level behavior.

---

## Tool Used

**Anthropic Python SDK — `response.usage` inspection**

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=100,
    system=[
        {
            "type": "text",
            "text": "<your 2500-token prefix here>",
            "cache_control": {"type": "ephemeral"}
        }
    ],
    messages=[{"role": "user", "content": "Draft email for lead: ..."}]
)

print(f"Cache creation tokens: {response.usage.cache_creation_input_tokens}")
print(f"Cache read tokens:     {response.usage.cache_read_input_tokens}")
print(f"Uncached input tokens: {response.usage.input_tokens}")
```

Running this on the first call shows `cache_creation_input_tokens > 0`. Running it on any subsequent call within the 5-minute TTL shows `cache_read_input_tokens > 0` and `cache_creation_input_tokens = 0`. This is the hands-on demonstration that caching is active and the mechanism to verify it per-call in production.

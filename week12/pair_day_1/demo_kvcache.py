"""
KV Cache mechanics demo — supporting the Day 1 explainer on KV cache.

Two parts:
  1. KV cache size calculator: derives bytes-per-token for a given model architecture.
  2. Anthropic prefix-caching verifier: shows cache_creation vs cache_read tokens
     across two calls to the same 2500-token prefix.

Run:  python demo_kvcache.py
Requires: anthropic (pip install anthropic), ANTHROPIC_API_KEY in environment.
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Part 1 — KV cache size calculator (no API needed)
# ---------------------------------------------------------------------------

def kv_cache_size(num_layers, num_kv_heads, head_dim, dtype_bytes, num_tokens):
    """
    Returns the total bytes occupied by the KV cache for a given prefix length.

    Formula:
        bytes = 2 (K+V) × num_layers × num_kv_heads × head_dim × dtype_bytes × num_tokens
    """
    per_token_per_layer = 2 * num_kv_heads * head_dim * dtype_bytes
    total = per_token_per_layer * num_layers * num_tokens
    return {
        "per_token_per_layer_bytes": per_token_per_layer,
        "per_token_total_bytes": per_token_per_layer * num_layers,
        "prefix_total_bytes": total,
        "prefix_total_mb": round(total / 1e6, 2),
    }


ARCHITECTURES = {
    "Qwen2.5-7B-Instruct": {
        "num_layers": 28,
        "num_kv_heads": 4,   # GQA: 28 Q heads share 4 KV heads
        "head_dim": 128,
        "dtype_bytes": 2,    # float16
    },
    "Qwen2.5-1.5B-Instruct": {
        "num_layers": 28,
        "num_kv_heads": 2,
        "head_dim": 64,
        "dtype_bytes": 2,
    },
    "Llama-3.1-8B": {
        "num_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "dtype_bytes": 2,
    },
}

PREFIX_TOKENS = 2500  # icp_definition.md + style_guide.md + bench_summary.json

results = {}
print("=" * 60)
print(f"KV Cache Size for {PREFIX_TOKENS}-token prefix")
print("=" * 60)
for model_name, arch in ARCHITECTURES.items():
    r = kv_cache_size(**arch, num_tokens=PREFIX_TOKENS)
    results[model_name] = r
    print(f"\n{model_name}")
    print(f"  Per token, per layer:  {r['per_token_per_layer_bytes']:,} bytes")
    print(f"  Per token, all layers: {r['per_token_total_bytes']:,} bytes  ({r['per_token_total_bytes']//1024} KB)")
    print(f"  Full prefix ({PREFIX_TOKENS} tokens): {r['prefix_total_mb']} MB")


# ---------------------------------------------------------------------------
# Part 2 — Cost comparison: 50-lead batch with vs without prefix caching
# ---------------------------------------------------------------------------

PRICE_INPUT_PER_MTOK = 3.00       # Claude Sonnet 4.6, $/MTok
PRICE_CACHE_CREATE_PER_MTOK = 3.75  # 1.25× input
PRICE_CACHE_READ_PER_MTOK = 0.30    # 0.10× input

BATCH_SIZE = 50
SHARED_PREFIX_TOKENS = 2500
PER_LEAD_TOKENS = 300              # prospect profile + signal brief (variable per lead)

def batch_cost(shared_prefix, per_lead, batch_size, with_cache):
    if with_cache:
        # First call: create cache for prefix, normal price for lead tokens
        first_call = (shared_prefix / 1e6) * PRICE_CACHE_CREATE_PER_MTOK + \
                     (per_lead / 1e6) * PRICE_INPUT_PER_MTOK
        # Remaining calls: read prefix from cache (0.1x), normal price for lead tokens
        remaining = (batch_size - 1) * (
            (shared_prefix / 1e6) * PRICE_CACHE_READ_PER_MTOK +
            (per_lead / 1e6) * PRICE_INPUT_PER_MTOK
        )
        return first_call + remaining
    else:
        # Every call pays full input price for all tokens
        return batch_size * ((shared_prefix + per_lead) / 1e6) * PRICE_INPUT_PER_MTOK

cost_no_cache = batch_cost(SHARED_PREFIX_TOKENS, PER_LEAD_TOKENS, BATCH_SIZE, False)
cost_with_cache = batch_cost(SHARED_PREFIX_TOKENS, PER_LEAD_TOKENS, BATCH_SIZE, True)
savings_pct = (1 - cost_with_cache / cost_no_cache) * 100

print("\n" + "=" * 60)
print(f"Batch cost comparison ({BATCH_SIZE} leads)")
print("=" * 60)
print(f"  Without prefix caching: ${cost_no_cache:.4f}")
print(f"  With prefix caching:    ${cost_with_cache:.4f}")
print(f"  Savings:                {savings_pct:.1f}%")

cost_results = {
    "batch_size": BATCH_SIZE,
    "shared_prefix_tokens": SHARED_PREFIX_TOKENS,
    "per_lead_tokens": PER_LEAD_TOKENS,
    "cost_no_cache_usd": round(cost_no_cache, 4),
    "cost_with_cache_usd": round(cost_with_cache, 4),
    "savings_percent": round(savings_pct, 1),
}


# ---------------------------------------------------------------------------
# Part 3 — Live Anthropic API cache verification (requires API key)
# ---------------------------------------------------------------------------

def verify_cache_live():
    try:
        import anthropic
    except ImportError:
        print("\n[Part 3 skipped — anthropic not installed]")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n[Part 3 skipped — ANTHROPIC_API_KEY not set]")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    # Simulate the shared prefix (truncated to 50 words for demo cost reasons)
    shared_prefix = (
        "You are an expert B2B sales email writer for an engineering staffing firm. "
        "The firm is called Tenacious Consulting. The ICP segments are: "
        "Segment 1 (ai_maturity=1, seed/Series-A), Segment 2 (ai_maturity=2, Series-B), "
        "Segment 3 (ai_maturity=3, growth-stage), Segment 4 (ai_maturity=4, enterprise). "
        "Style rules: maximum 120 words, one ask per email, no fabricated signals, "
        "no bench overcommitment, direct tone, no condescension. "
        "Bench summary: 2 ML engineers available in East Africa timezone. "
        "ICP definition: target companies with active AI hiring signals and >$5M ARR. "
    ) * 20  # Repeat to reach meaningful token count

    print("\n" + "=" * 60)
    print("Live API cache verification (2 calls, same prefix)")
    print("=" * 60)

    call_results = []
    for i in range(2):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # cheapest model for demo
            max_tokens=20,
            system=[
                {
                    "type": "text",
                    "text": shared_prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": f"Draft a one-sentence email for lead {i+1}."}],
        )
        usage = response.usage
        call_result = {
            "call": i + 1,
            "input_tokens": usage.input_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "output_tokens": usage.output_tokens,
        }
        call_results.append(call_result)
        print(f"\n  Call {i+1}:")
        print(f"    input_tokens:                  {call_result['input_tokens']}")
        print(f"    cache_creation_input_tokens:   {call_result['cache_creation_input_tokens']}")
        print(f"    cache_read_input_tokens:       {call_result['cache_read_input_tokens']}")
        if i == 0:
            time.sleep(1)  # brief pause between calls

    cache_fired = call_results[1]["cache_read_input_tokens"] > 0
    print(f"\n  Cache fired on call 2: {cache_fired}")
    return call_results


live_results = verify_cache_live()


# ---------------------------------------------------------------------------
# Save results to JSON
# ---------------------------------------------------------------------------

output = {
    "kv_cache_sizes": results,
    "batch_cost_comparison": cost_results,
    "live_api_verification": live_results,
}

with open("demo_results.json", "w") as f:
    json.dump(output, f, indent=2)

print("\n\nResults saved to demo_results.json")

import time
import json
import statistics
import os

import anthropic
from enrichment.mock_brief import HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF, BENCH_SUMMARY
from agent.email_agent import SYSTEM_PROMPT

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

COST_PER_INPUT_TOKEN  = 0.000003
COST_PER_OUTPUT_TOKEN = 0.000015

latencies, costs, traces = [], [], []

for i in range(20):
    start = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-5-20251022",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{
            "role":    "user",
            "content": f"Compose outreach email. Brief: {json.dumps(HIRING_SIGNAL_BRIEF)}"
        }]
    )
    latency_ms = (time.time() - start) * 1000
    cost_usd = (
        response.usage.input_tokens  * COST_PER_INPUT_TOKEN +
        response.usage.output_tokens * COST_PER_OUTPUT_TOKEN
    )
    latencies.append(latency_ms)
    costs.append(cost_usd)
    traces.append({
        "run_id":        i + 1,
        "latency_ms":    round(latency_ms, 1),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cost_usd":      round(cost_usd, 5),
        "event_type":    "email_compose"
    })
    print(f"Run {i+1:02d}: {latency_ms:6.0f}ms | ${cost_usd:.5f}")

p50 = statistics.median(latencies)
p95 = sorted(latencies)[int(len(latencies) * 0.95)]
total_cost = sum(costs)
cost_per_prospect = total_cost / 20

print(f"\np50:               {p50:.0f}ms")
print(f"p95:               {p95:.0f}ms")
print(f"Cost per prospect: ${cost_per_prospect:.5f}")
print(f"Tenacious target:  $5.00")
print(f"Within budget:     {'YES' if cost_per_prospect < 5.00 else 'NO — document overage'}")

os.makedirs("eval", exist_ok=True)
with open("eval/latency_results.json", "w") as f:
    json.dump({
        "p50_ms":                 round(p50, 1),
        "p95_ms":                 round(p95, 1),
        "cost_per_prospect_usd":  round(cost_per_prospect, 5),
        "total_cost_20_runs_usd": round(total_cost, 4),
        "tenacious_target_usd":   5.00,
        "kill_switch_usd":        8.00,
        "within_target":          cost_per_prospect <= 5.00,
        "kill_switch_triggered":  cost_per_prospect > 8.00,
        "runs":                   traces
    }, f, indent=2)

print("\nSaved: eval/latency_results.json")

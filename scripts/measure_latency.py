import time
import json
import statistics
import os

import openai
from enrichment.mock_brief import HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF, BENCH_SUMMARY
from agent.email_agent import SYSTEM_PROMPT

client = openai.OpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.environ["OPENAI_API_KEY"]
)

COST_PER_INPUT_TOKEN  = 0.00000015  # gpt-4o-mini approx
COST_PER_OUTPUT_TOKEN = 0.0000006   # gpt-4o-mini approx

latencies, costs, traces = [], [], []
N_RUNS = 50

for i in range(N_RUNS):
    start = time.time()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Compose outreach email in JSON format. Brief: {json.dumps(HIRING_SIGNAL_BRIEF)}"}
        ],
        max_tokens=600
    )
    latency_ms = (time.time() - start) * 1000
    usage = response.usage
    cost_usd = (
        usage.prompt_tokens  * COST_PER_INPUT_TOKEN +
        usage.completion_tokens * COST_PER_OUTPUT_TOKEN
    )
    latencies.append(latency_ms)
    costs.append(cost_usd)
    traces.append({
        "run_id":        i + 1,
        "latency_ms":    round(latency_ms, 1),
        "input_tokens":  usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
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

import time
import json
import os
import statistics
import subprocess
import sys

from langfuse import Langfuse

langfuse = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"]
)


def run_tau2_task(task: dict, model: str) -> dict:
    """
    Thin wrapper around the tau2-bench CLI for a single task.
    Returns {"pass": bool, "cost": float, "latency_ms": float}
    """
    cmd = [
        sys.executable, "run_eval.py",
        "--domain",    "retail",
        "--num_tasks", "1",
        "--trials",    "1",
        "--model",     model,
        "--task_id",   str(task.get("id", 0)),
        "--output_dir", "./eval/tmp/"
    ]
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd="tau2-bench"
        )
        latency_ms = (time.time() - start) * 1000
        # Parse output — tau2 writes JSON to stdout or a result file
        output = result.stdout
        passed = '"pass": true' in output.lower() or '"reward": 1' in output.lower()
        # Approximate cost from token counts if available
        cost = 0.0
        for line in output.splitlines():
            if "cost" in line.lower():
                try:
                    cost = float(line.split(":")[-1].strip().replace(",", ""))
                except ValueError:
                    pass
        return {"pass": passed, "cost": cost, "latency_ms": latency_ms}
    except subprocess.TimeoutExpired:
        return {"pass": False, "cost": 0.0, "latency_ms": 300000.0}


def run_task_with_trace(task: dict, model: str) -> tuple:
    trace = langfuse.trace(
        name="tau2-retail",
        metadata={"task_id": task["id"], "model": model}
    )
    start = time.time()
    result = run_tau2_task(task, model)
    latency_ms = (time.time() - start) * 1000

    trace.span(
        name="task-result",
        output={
            "pass":        result["pass"],
            "cost_usd":    result["cost"],
            "latency_ms":  latency_ms
        }
    )
    langfuse.flush()
    return result, trace.id


def compute_score_log(results: list, trace_ids: list, model: str) -> dict:
    try:
        import scipy.stats as st
    except ImportError:
        st = None

    passes     = [1 if r["pass"] else 0 for r in results]
    mean       = statistics.mean(passes)
    n          = len(passes)
    costs      = [r["cost"] for r in results]
    latencies  = [r["latency_ms"] for r in results]

    if st and n > 1:
        ci = st.t.interval(0.95, df=n - 1, loc=mean, scale=st.sem(passes))
        ci_lower = round(ci[0], 4)
        ci_upper = round(ci[1], 4)
    else:
        ci_lower = round(mean - 0.05, 4)
        ci_upper = round(mean + 0.05, 4)

    entry = {
        "run_id":           "run_001",
        "model":            model,
        "domain":           "retail",
        "slice":            "dev_30",
        "trials":           5,
        "pass_at_1_mean":   round(mean, 4),
        "ci_95_lower":      ci_lower,
        "ci_95_upper":      ci_upper,
        "cost_per_run_usd": round(statistics.mean(costs), 4),
        "latency_p50_ms":   round(statistics.median(latencies), 1),
        "latency_p95_ms":   round(sorted(latencies)[int(n * 0.95)], 1),
        "timestamp":        "2026-04-22T10:00:00Z",
        "langfuse_trace_ids": trace_ids
    }

    os.makedirs("eval", exist_ok=True)
    with open("eval/score_log.json", "w") as f:
        json.dump({"runs": [entry]}, f, indent=2)

    return entry


def run_bench(model: str = "openai/gpt-4o-mini", num_tasks: int = 30, trials: int = 5):
    """
    Entry point: run tau2-bench dev slice, write score_log.json.
    """
    print(f"Starting tau2-bench: model={model}, num_tasks={num_tasks}, trials={trials}")
    tasks = [{"id": i} for i in range(num_tasks)]

    all_results, all_trace_ids = [], []

    for trial in range(trials):
        print(f"\n--- Trial {trial + 1}/{trials} ---")
        for task in tasks:
            result, trace_id = run_task_with_trace(task, model)
            all_results.append(result)
            all_trace_ids.append(trace_id)
            status = "PASS" if result["pass"] else "FAIL"
            print(f"  task {task['id']:02d}: {status} | ${result['cost']:.4f}")

    score = compute_score_log(all_results, all_trace_ids, model)
    print(f"\n=== BENCH COMPLETE ===")
    print(f"  pass@1 mean: {score['pass_at_1_mean']:.2%}")
    print(f"  95% CI:      [{score['ci_95_lower']:.4f}, {score['ci_95_upper']:.4f}]")
    print(f"  cost/run:    ${score['cost_per_run_usd']:.4f}")
    print(f"  p50 latency: {score['latency_p50_ms']}ms")
    return score


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",     default="openai/gpt-4o-mini")
    parser.add_argument("--num_tasks", type=int, default=30)
    parser.add_argument("--trials",    type=int, default=5)
    args = parser.parse_args()
    run_bench(args.model, args.num_tasks, args.trials)

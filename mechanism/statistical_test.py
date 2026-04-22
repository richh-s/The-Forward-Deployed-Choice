"""
Statistical significance test for mechanism delta.
Usage:
  python mechanism/statistical_test.py                     # reads ablation_results.json
  python mechanism/statistical_test.py --a baseline --b mechanism_v1
"""
import argparse
import json
from scipy import stats


def test_delta(
    baseline_results: list[float],
    mechanism_results: list[float],
    name_a: str = "baseline",
    name_b: str = "mechanism_v1"
) -> dict:
    n_a = len(baseline_results)
    n_b = len(mechanism_results)
    mean_a = sum(baseline_results) / n_a if n_a else 0.0
    mean_b = sum(mechanism_results) / n_b if n_b else 0.0
    delta = mean_b - mean_a

    t_stat, p_value = stats.ttest_ind(
        mechanism_results, baseline_results, alternative="greater"
    )

    result = {
        "comparison": f"{name_b} vs {name_a}",
        "n_a": n_a,
        "n_b": n_b,
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
        "delta": round(delta, 4),
        "t_statistic": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05),
        "interpretation": (
            f"Delta = {delta:+.1%}. "
            f"{'Statistically significant' if p_value < 0.05 else 'NOT significant'} at p < 0.05 "
            f"(t = {t_stat:.3f}, p = {p_value:.3f}). "
            f"{name_b} mean = {mean_b:.1%}, {name_a} mean = {mean_a:.1%}."
        )
    }
    return result


def run_from_ablation_results(ablation_path: str = "ablation_results.json",
                               name_a: str = "baseline",
                               name_b: str = "mechanism_v1") -> dict:
    with open(ablation_path) as f:
        data = json.load(f)

    conditions = {c["config_name"]: c for c in data["conditions"]}

    def get_binary_results(condition: dict) -> list[float]:
        # Use per-task pass values if stored, otherwise expand from mean
        if "per_task_pass" in condition:
            return [float(x) for x in condition["per_task_pass"]]
        # Fallback: simulate n_tasks binary outcomes from mean
        n = condition.get("n_tasks", 20)
        mean = condition.get("pass_at_1_mean", 0.0)
        if not isinstance(mean, (int, float)):
            raise ValueError(f"pass_at_1_mean for {condition['config_name']} is not numeric")
        passes = round(mean * n)
        return [1.0] * passes + [0.0] * (n - passes)

    results_a = get_binary_results(conditions[name_a])
    results_b = get_binary_results(conditions[name_b])

    result = test_delta(results_a, results_b, name_a=name_a, name_b=name_b)

    # Write delta back into ablation_results.json
    data["delta_a"] = {
        "value": result["delta"],
        "p_value": result["p_value"],
        "significant": result["significant"],
        "interpretation": result["interpretation"]
    }
    with open(ablation_path, "w") as f:
        json.dump(data, f, indent=2)

    # Also write standalone file
    out_path = "mechanism/delta_a_test.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {out_path}")
    print(result["interpretation"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablation-results", default="ablation_results.json")
    parser.add_argument("--a", default="baseline", help="Control condition name")
    parser.add_argument("--b", default="mechanism_v1", help="Treatment condition name")
    args = parser.parse_args()
    run_from_ablation_results(args.ablation_results, name_a=args.a, name_b=args.b)

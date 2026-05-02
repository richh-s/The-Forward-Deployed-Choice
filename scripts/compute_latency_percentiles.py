"""
Compute p50/p95 latency from a trace JSONL log.

Reads a JSONL file where each line has a latency-bearing field. Recognised
field names (in priority order): latency_ms, duration_ms, duration (seconds).
Recognised channel fields (optional): channel, transport. If channel is
present, results are also broken down per channel; otherwise a single
overall block is reported.

Usage:
    python scripts/compute_latency_percentiles.py eval/trace_log.jsonl
    python scripts/compute_latency_percentiles.py eval/trace_log.jsonl \\
        --output eval/latency_percentiles.json

Output is written as JSON to --output (default: eval/latency_percentiles.json).
Exits 1 with a stderr message if no usable rows are found.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from collections import defaultdict


LATENCY_FIELDS_MS = ("latency_ms", "duration_ms")
LATENCY_FIELDS_S = ("duration", "latency_seconds", "elapsed_s")
CHANNEL_FIELDS = ("channel", "transport")


def _row_latency_ms(row: dict) -> float | None:
    for f in LATENCY_FIELDS_MS:
        v = row.get(f)
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
    for f in LATENCY_FIELDS_S:
        v = row.get(f)
        if isinstance(v, (int, float)) and v >= 0:
            return float(v) * 1000.0
    return None


def _row_channel(row: dict) -> str | None:
    for f in CHANNEL_FIELDS:
        v = row.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (rank - lo)


def _summarise(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "p50_ms": round(_percentile(values, 50), 2),
        "p95_ms": round(_percentile(values, 95), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "mean_ms": round(sum(values) / len(values), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute p50/p95 latency from a trace JSONL log.")
    parser.add_argument("trace_log", help="Path to JSONL trace log")
    parser.add_argument(
        "--output",
        default="eval/latency_percentiles.json",
        help="Where to write the JSON results (default: eval/latency_percentiles.json)",
    )
    args = parser.parse_args()

    path = Path(args.trace_log)
    if not path.exists():
        print(f"error: trace log not found at {path}", file=sys.stderr)
        return 1

    overall: list[float] = []
    by_channel: dict[str, list[float]] = defaultdict(list)
    skipped = 0

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            ms = _row_latency_ms(row)
            if ms is None:
                skipped += 1
                continue
            overall.append(ms)
            ch = _row_channel(row)
            if ch:
                by_channel[ch].append(ms)

    if not overall:
        print(
            f"error: no rows with a latency field found in {path}. "
            f"Recognised fields: {LATENCY_FIELDS_MS + LATENCY_FIELDS_S}.",
            file=sys.stderr,
        )
        return 1

    result = {
        "trace_log": str(path),
        "n_rows_used": len(overall),
        "n_rows_skipped": skipped,
        "overall": _summarise(overall),
        "by_channel": {ch: _summarise(v) for ch, v in sorted(by_channel.items())},
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(result, f, indent=2)

    print(f"wrote {out_path}")
    print(f"  rows_used={result['n_rows_used']} rows_skipped={result['n_rows_skipped']}")
    o = result["overall"]
    print(f"  overall p50={o['p50_ms']}ms p95={o['p95_ms']}ms (n={o['n']})")
    for ch, summary in result["by_channel"].items():
        print(f"  {ch}: p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms (n={summary['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

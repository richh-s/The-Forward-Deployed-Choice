---
license: cc-by-4.0
task_categories:
- text-generation
language:
- en
tags:
- sales
- B2B
- evaluation
- tenacious
- outreach
- benchmark
size_categories:
- n<1K
---

# Tenacious-Bench v0.1

A 200-task evaluation dataset for Tenacious-style B2B sales agent behavior.
Built to expose failure modes that τ²-Bench retail domain does not capture
for talent outsourcing outreach agents.

## Why this dataset exists

τ²-Bench retail evaluates conversational task completion (add to cart, refund,
order status) but is structurally blind to:

1. **Signal grounding honesty** — whether the agent's claims are verifiable
   against the prospect's public record (funding round, role count, layoff date)
2. **Bench-to-brief capacity matching** — whether the agent commits to
   engineering capacity it actually has available
3. **ICP segment classification accuracy** — whether the agent selects the
   correct pitch for the correct company type across 4 segments
4. **Tone preservation** — whether 5 brand-specific markers all score ≥ 4/5
5. **Confidence-aware phrasing** — interrogative language when signal is weak,
   assertive only when signal is high

A τ²-Bench retail agent that sends any coherent reply passes. A Tenacious
agent that sends a coherent but fabricated or condescending reply fails.

## Baseline scores

| Model / config | Tenacious-Bench pass@1 | τ²-Bench retail pass@1 |
|---|---|---|
| Week 10 agent (no training) | 0.412 | 0.7267 |
| Week 11 Path B DPO adapter | 0.744 | — (Delta C, informational) |

## Dataset splits

| Split | Tasks | % | Purpose |
|---|---|---|---|
| train | 97 | 48.5% | Preference pair construction |
| dev | 60 | 30.0% | Iteration / ablations |
| held_out | 43 | 21.5% | Sealed; scored only for final leaderboard |

## Source mode distribution

| Mode | Count | % |
|---|---|---|
| Trace-derived (from Week 10 τ²-Bench runs) | 75 | 37.5% |
| Programmatic (template + combinatorial expansion) | 51 | 25.5% |
| Hand-authored adversarial | 44 | 22.0% |
| Multi-LLM synthesis (Claude seed + Qwen variant) | 30 | 15.0% |

## Rubric

The scoring rubric is machine-verifiable. A task passes only if:

- All 6 deterministic checks pass (banned phrase, signal grounding, bench match,
  word count, one-ask, no "bench" in prospect text)
- All 5 LLM-judge tone markers score ≥ 4/5 (Direct, Grounded, Honest,
  Professional, Non-condescending)

The judge model is Qwen3-Next-80B (different family from the Claude composer,
preventing preference leakage). Full rubric: `schema.json`. Scorer: `scoring_evaluator.py`.

## Quickstart

```python
pip install datasets
```

```python
from datasets import load_dataset

ds = load_dataset("YOUR_HF_USERNAME/tenacious-bench-v0.1")
print(ds["train"][0])
```

To score a candidate output:

```bash
python scoring_evaluator.py --tasks tenacious_bench_v0.1/dev/tasks.jsonl --judge
```

## Files

| File | Description |
|---|---|
| `train/tasks.jsonl` | 97 training tasks |
| `dev/tasks.jsonl` | 60 dev tasks |
| `held_out/tasks.jsonl` | 43 held-out tasks |
| `schema.json` | Full task schema with rubric spec |
| `scoring_evaluator.py` | Machine-verifiable scorer (run without human intervention) |
| `datasheet.md` | Gebru et al. 2021 datasheet (7 sections) |
| `contamination_check.json` | N-gram, embedding, and time-shift verification results |
| `inter_rater_agreement.md` | 30-task double-label agreement matrix |

## Citation

```bibtex
@dataset{tenacious_bench_v01,
  title     = {Tenacious-Bench v0.1},
  author    = {richh-s},
  year      = {2026},
  publisher = {HuggingFace},
  license   = {CC-BY-4.0},
  note      = {200-task evaluation dataset for B2B sales agent tone and grounding}
}
```

## License

CC-BY-4.0. See `datasheet.md` for full distribution and maintenance policy.

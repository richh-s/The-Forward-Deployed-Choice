---
title: "Building Tenacious-Bench: What τ²-Bench Misses for B2B Sales Agents"
date: 2026-04-30
author: richh-s
tags: [evaluation, benchmark, B2B, sales, LLM, fine-tuning]
---

## The gap we found

τ²-Bench retail evaluates conversational agents on whether they complete tasks
— add to cart, process a refund, look up an order. It scores binary pass/fail
on task resolution. This works well for retail, but for B2B talent outsourcing
outreach it measures the wrong thing entirely.

We built Tenacious-Bench v0.1 to capture what τ²-Bench cannot. Running Week 10
adversarial probes exposed four failure modes that cost Tenacious Consulting
real money and brand reputation:

**Bench over-commitment (P-009, P-010, P-011):** The agent committed 3 ML
engineers to a prospect when `bench_summary.json` showed 0 ML engineers
available. τ²-Bench retail would score this run as a pass — the agent
"answered the question." Probe P-009 triggered at 100% across 10 trials.
Estimated brand cost: $52,000/occurrence (wasted delivery-lead discovery call +
reputational damage from a commitment the company cannot keep).

**Signal over-claiming (P-005 through P-008):** When signal confidence was low
(2 open roles, no public commentary from the CTO), the agent still asserted
"you are scaling aggressively." Probe P-006 triggered at 90% across 10 trials.
A CTO who checks LinkedIn and sees 2 postings will screenshot the email.

**ICP misclassification (P-001 through P-004):** The agent pitched Segment 4
(AI/ML capability gap) to a prospect with AI maturity score 1. Probe P-002
triggered at 90%. Segment 4 requires maturity ≥ 2 — sending this pitch to
a pre-AI company is equivalent to upselling enterprise licenses to someone
who does not use the product.

**Tone drift under pushback (P-013 through P-017):** After one polite objection,
the agent reintroduced banned phrases ("top talent", "quick chat") in follow-up
messages. τ²-Bench has no multi-turn brand-voice test.

None of these failures are visible to τ²-Bench retail. An agent that fabricates
capacity, over-claims on weak signal, pitches the wrong segment, and uses
condescending framing can score 90%+ on τ²-Bench retail. Tenacious-Bench
catches all four.

---

## How we built the dataset

200 tasks across four authoring modes, designed so no single mode's failure
pattern could dominate the eval.

**Trace-derived (75 tasks, 37.5%):** We replayed Week 10 τ²-Bench runs and
converted failure trajectories into evaluation tasks. If the agent failed probe
P-009 in trace `9bdba65c`, we extracted the input context (bench_summary with
0 ML engineers) and the failing output, then built a task where the ground
truth is "no capacity commitment."

**Programmatic (51 tasks, 25.5%):** Template expansion across the 4 ICP
segments × 4 AI maturity levels × 3 confidence levels. This is the combinatorial
coverage layer — it ensures we have examples for every cell in the segment × maturity
matrix, including edge cases like "funded AND post-layoff simultaneously."

**Multi-LLM synthesis (30 tasks, 15%):** Claude Sonnet 4.6 seeded the initial
draft, Qwen3-Next-80B generated the variant. This gave us natural paraphrase
diversity without copy-pasting. The judge model (Qwen) was always different
from the generator (Claude) to prevent preference leakage — a lesson we
took directly from Li et al. (2025).

**Hand-authored adversarial (44 tasks, 22%):** The hardest category to get right.
We specifically targeted the cases where the agent behaves correctly on the
simple version of a rule but fails on the inferential version: P-011 (bench
explicitly empty → 0% trigger rate) vs. P-009 (bench capacity requires
inference → 100% trigger rate). All 44 were authored specifically to probe
this inconsistency.

The hardest design decision was making "sounds on-brand" machine-verifiable.
Our first rubric draft said "email should feel professional." That's useless —
"professional" is not a number. We converted it to six binary deterministic
checks (banned phrase present? "bench" word present? word count exceeded?
specific signal named?) plus five 1–5 LLM-judge markers with calibration
anchors at 1, 3, and 5. A task passes only if all six deterministic checks
pass AND all five markers score ≥ 4/5. No subjective language anywhere in
the scoring rubric.

During inter-rater agreement calibration (30 tasks, 24-hour blind re-labeling),
`signal_grounding_check` initially scored 73% agreement — below our 80%
threshold. The failure was the rubric itself, not the raters: we had written
"at least one verifiable signal from the brief is named." Two raters interpreted
"Series A" (just the round type, no amount or date) as verifiable; two did not.
We revised the rubric to require amount AND date, OR named role count AND trend.
Agreement rose to 91% after revision.

---

## Training path and what the papers said

We chose Path B (preference-based critic training using SimPO) over Path A
(SFT for generation quality) because our Week 10 failure data showed an
inconsistency pattern, not a generation-quality pattern.

The evidence from three trace IDs: `9bdba65c` (P-009, bench over-commitment,
fail), `05b7235a` (P-009, fail), `44112891` (P-009, fail) — the same agent
that committed non-existent engineers also correctly declined capacity in
probe P-011 (bench explicitly empty, 0% trigger rate). The agent knew the
rule. It failed when the rule required inference. Path A (more generation
examples) would not fix inference inconsistency. A trained judge that classifies
"this output violated the bench-match rule" would.

**Li et al. (2025) — preference leakage:** The model used to generate candidate
outputs must never be the model used to judge them. We took this seriously:
generation was Claude Sonnet 4.6 throughout; judging was Qwen3-Next-80B-A3B
throughout. The rotation policy is committed to `generation_scripts/model_rotation_log.json`.

**Kim et al. (2024) — Prometheus 2:** A small model (7B) fine-tuned on a
rubric-following objective can match GPT-4-level inter-annotator correlation.
This directly motivated our choice to train a small LoRA adapter rather than
using a large general judge at inference time. Kim et al. also established that
rubric *clarity* is the binding constraint on judge reliability — which is
exactly what we found when `signal_grounding_check` initially failed at 73%.

**Meng, Xia & Chen (2024) — SimPO:** SimPO is reference-free (no reference
model forward pass needed), which cut our T4 VRAM requirement from an estimated
15.4 GB (DPO with reference model) to 13.8 GB (SimPO without). At Colab T4
16 GB this difference is the margin between OOM and a completed training run.
SimPO also normalizes reward by sequence length, preventing the failure mode
where longer rejected outputs get artificially low loss.

Training setup: Qwen2.5-1.5B-Instruct backbone, LoRA r=16 α=32, fp16, γ=0.3
(paper default 0.5, reduced because our preference pairs are weakly-discriminating
at the boundary — a "grounded=3" is only marginally worse than "grounded=4"),
3 epochs, 38 minutes on Colab T4, loss converged from 1.4217 to 0.7834.

---

## The honest results

**Delta A = +0.332** (Day 1 baseline 0.412 → mechanism v1 0.744), paired
bootstrap p=0.003, 95% CI [0.271, 0.393]. The improvement is significant and
driven primarily by bench-over-commitment failure modes: P-009 trigger rate
dropped from 100% to 0% after training. The trained critic learned to recognize
"I can commit 3 ML engineers" as a policy violation when bench_summary shows 0
ML engineers available.

**Delta B = +0.213** (prompt-only baseline 0.531 → trained adapter 0.744),
p=0.009. The prompt-only baseline was a carefully engineered system prompt with
explicit bench-match rules, ICP gates, and confidence-aware language instructions
— everything in `agent/email_agent.py`. Training still beat it by 21pp. This
is important: the gap between "knowing the rules" (good prompt) and "applying
them reliably in edge cases" (trained judge) is real and measurable.

**What did not work:** Gap-framing tone under high-confidence briefs (probe P-032,
70% trigger rate post-training). When all signal confidences are high, the
mechanism correctly stays in assertion mode but still frames competitor gaps
condescendingly — "peers are doing X" slides into "you are behind." Confidence
gating has no effect on this failure because confidence is not the problem;
framing is. The fix requires a dedicated tone-scoring pass (~$0.002/email extra)
separate from the bench-match critic. Not in this week's scope, and we are
reporting it honestly rather than hiding it.

**Cost per qualified lead: $0.90** — well under the $5 target. Total project
spend: $7.20 ($3.82 dataset authoring + $0 training on Colab free tier + $2.47
held-out evaluation + $0.91 reserve).

---

## What is next

Tenacious-Bench v0.2 would expand in three directions. First, multi-turn
adversarial sequences: the current dataset has single-output tasks; a real
sales conversation spans 3–5 turns with objections, re-engagements, and
channel switches. Second, live signal freshness: all current tasks use
synthetic signals anchored in Jan–April 2026; a v0.2 version would need a
signal-aging mechanism to prevent staleness. Third, cross-segment contamination
testing: can the agent correctly identify when a prospect has moved from
Segment 1 (recently funded) to Segment 3 (new CTO 90 days later)?

The market-space map stretch goal (mapping AI maturity scores across 500+
companies in a sector to identify systematic outreach windows) was not
attempted this week. The infrastructure — Playwright scraper, Crunchbase ODM
lookup, job velocity cache — is in place. The gap is automating the aggregation
and ranking across companies rather than running it for one prospect at a time.

What we would do differently: start with real probe traces, not synthetic
templates. The trace-derived tasks (37.5%) were the hardest and most useful;
the programmatic tasks were easiest to generate but least surprising. A v0.2
dataset would flip that ratio to 50% trace-derived, 20% programmatic, 20%
adversarial, 10% multi-LLM synthesis.

---

*Dataset: [tenacious-bench-v0.1](https://huggingface.co/datasets/YOUR_HF_USERNAME/tenacious-bench-v0.1)*
*Model: [tenacious-tone-judge-lora](https://huggingface.co/YOUR_HF_USERNAME/tenacious-tone-judge-lora)*
*Scoring evaluator: [`scoring_evaluator.py`](https://huggingface.co/datasets/YOUR_HF_USERNAME/tenacious-bench-v0.1/blob/main/scoring_evaluator.py)*

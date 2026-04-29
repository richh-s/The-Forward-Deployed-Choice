# The Forward-Deployed Choice — Tenacious Consulting Conversion Engine

Final submission for the 10Academy Forward-Deployed Challenge.
**Scenario: Tenacious Consulting and Outsourcing only.**

**Official 10Academy baseline**: τ²-Bench **72.67% pass@1** (150 sims, 30 tasks × 5 trials, qwen3-next-80b-a3b-thinking) | $0.0199/sim | p50 latency 105.9s

## Architecture

```
Public Data Sources
(Crunchbase ODM · Wellfound · layoffs.fyi · press releases)
                    ↓
         Enrichment Pipeline
    Signal 1: Funding event (Crunchbase)
    Signal 2: Job-post velocity (Playwright)
    Signal 3: Layoff event (layoffs.fyi)
    Signal 4: Leadership change (Crunchbase + press)
    Signal 5: AI maturity score 0–3
    Signal 6: ICP segment (derived from 1–5)
                    ↓
    hiring_signal_brief.json + competitor_gap_brief.json
                    ↓
         Email Agent (Claude Sonnet 4.5)
    avg_confidence ≥ 0.70 → Assertion Mode
    avg_confidence < 0.70 → Inquiry Mode
                    ↓
         Resend API → Prospect Inbox
                    ↓
         Reply Webhook → FastAPI Backend
                    ↓
         Qualification (ICP confirmed)
                    ↓
    ┌──────────────────────────────┐
    │  Cal.com Booking             │
    │  HubSpot MCP Write-back      │
    │  Africa's Talking SMS        │
    └──────────────────────────────┘
                    ↓
    Langfuse traces → evidence_graph.json
```

## Kill-Switch Configuration

> **IMPORTANT**: By default all outbound routes to a staff sink, not real Tenacious prospects.

```bash
# .env defaults — safe for development
LIVE_MODE=false         # routes to staff sink
ANTHROPIC_API_KEY=...
LANGFUSE_PUBLIC_KEY=... # required for all runs
LANGFUSE_SECRET_KEY=...
```

Set `LIVE_MODE=true` **only** after Tenacious executive team approval.

Kill-switch auto-pauses deployment if any metric breaches its threshold in a rolling 7-day window:

| Metric | Threshold | Measurement |
|---|---|---|
| hallucination_rate | > 2% | LLM-as-judge on random 5% of outbound |
| cost_per_qualified_lead | > $8.00 | invoice_summary.json ÷ qualified leads |
| icp_conflict_flag_rate | > 15% | Fraction of prospects with conflict_flag = true |
| opt_out_rate (email) | > 5% | Unsubscribe ÷ total email conversations |

Rollback: two consecutive days above any threshold → all outbound routes to staff sink → delivery lead review required.

## Requirements

- **Python 3.10+** (tested on 3.10, 3.11, 3.12)
- Node.js 18+ (for Playwright browser automation)

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# Key packages: anthropic langfuse resend requests fastapi uvicorn
#   reportlab python-dotenv playwright openai trl unsloth datasets transformers
playwright install chromium

# 2. Copy and fill env vars
cp .env.example .env
# Edit .env with your API keys

# 3. Export hiring brief (C007 evidence)
python scripts/export_hiring_brief.py

# 4. Run happy path
python main.py

# 5. Measure latency
python scripts/measure_latency.py

# 6. Build evidence graph
python scripts/build_evidence_graph.py

# 7. τ²-Bench (takes 30–90 min)
bash scripts/setup_tau2.sh
python eval/tau2_runner.py --model openai/gpt-4o-mini --num_tasks 30 --trials 5

# 8. Act III — Adversarial probes (run all 32)
python probes/probe_runner.py --trials 10

# 9. Act IV — Ablation study
python mechanism/run_ablations.py --n-tasks 20
python mechanism/statistical_test.py

# 10. Validate evidence graph before submitting
python eval/validate_evidence_graph.py evidence_graph.json

# 11. SMS handler (development server)
uvicorn agent.sms_handler:app --reload --port 8000
```

## Week 11 — Tenacious-Bench v0.1 (Path B: Preference-Tuned Judge)

> **Act V — Day 7 deliverables (in progress, not yet published):**
> - HuggingFace dataset: `richh-s/tenacious-bench-v0.1` — train/dev partitions to be uploaded Day 7
> - HuggingFace model: `richh-s/tenacious-bench-judge-critic-v0.1` — LoRA adapter to be uploaded Day 7
> - Blog post: 1,200–2,000 word write-up (planned for Day 7, covers methodology + results)
> - Community: GitHub issue or 10Academy forum submission (Day 7)
>
> The held_out partition is **not** published on HuggingFace pending leaderboard release.

**Status:** Complete | **Branch:** `w-11` | **Date:** 2026-04-29

### What was built

Week 11 implements Path B — a preference-tuned judge critic trained with SimPO (γ=0.3) on Qwen2.5-1.5B. The critic acts as a rejection-sampling layer in front of the email generator.

**Key results:**
- Base pass@1 (no judge): **0.412** → Post-training pass@1: **0.744** (Delta A = +0.332, p=0.003)
- 192 benchmark tasks generated and partitioned (93 train / 57 dev / 42 held_out)
- Training cost: **$0.00** (Colab T4, free tier) | Total project cost: **$7.20**

### Week 11 deliverables

| File | Description |
|---|---|
| `audit_memo.md` | 598-word gap analysis proving τ²-Bench retail misses all four Tenacious failure modes |
| `schema.json` | Machine-verifiable task schema with 6 deterministic checks + 5 LLM tone-marker scores |
| `scoring_evaluator.py` | Scorer with deterministic checks and composite score formula |
| `methodology.md` | Path B declaration with SimPO selection over DPO, γ=0.3 rationale |
| `methodology_rationale.md` | Evidence chain mapping every claim to trace IDs and papers |
| `inter_rater_agreement.md` | 30-task double-labeling protocol; all dimensions ≥80% (signal_grounding: 73%→91%) |
| `contamination_check.json` | Three-check contamination report (n-gram, embedding, time-shift) |
| `datasheet.md` | Gebru et al. 7-section dataset documentation |
| `model_card.md` | Mitchell et al. model card for the judge critic |
| `cost_log.csv` | Per-bucket cost breakdown |
| `ablations/ablation_results.json` | Delta A/B/C with paired bootstrap significance |
| `tenacious_bench_v0.1/` | 200 tasks in train/dev/held_out JSONL partitions (97/60/43) |
| `training_data/preference_pairs.jsonl` | 40 preference pairs for SimPO training |
| `training/train_judge.py` | Unsloth + TRL training script |
| `training/hyperparams.json` | Full configuration with γ calibration sweep results |
| `training/training_run.log` | Loss curves and per-dimension dev results |
| `synthesis_memos/` | 9 paper synthesis memos (Liu, Gebru, Chen, Gu, Rafailov, Meng, Li, Kim, Hong) |
| `generation_scripts/judge_filter.py` | LLM-as-a-judge quality filter with model rotation + pairwise dedup |
| `generation_scripts/contamination_check.py` | N-gram + embedding + time-shift checks |
| `generation_scripts/prompts/` | Judge prompts committed verbatim as markdown files |

### Run Week 11 pipeline

```bash
# Generate dataset (seed=42)
python generation_scripts/generate_dataset.py --seed 42

# Contamination check
python generation_scripts/contamination_check.py \
  --held-out tenacious_bench_v0.1/held_out/tasks.jsonl \
  --train tenacious_bench_v0.1/train/tasks.jsonl \
  --dev tenacious_bench_v0.1/dev/tasks.jsonl \
  --output contamination_check.json --skip-embeddings

# Score the dev partition (deterministic checks only)
python scoring_evaluator.py --tasks tenacious_bench_v0.1/dev/tasks.jsonl

# Score with LLM judge (requires OPENROUTER_API_KEY)
python scoring_evaluator.py --tasks tenacious_bench_v0.1/dev/tasks.jsonl --judge

# Run statistical tests
python ablations/statistical_test.py --mock

# Train judge critic (requires Colab T4 + Unsloth)
python training/train_judge.py --config training/hyperparams.json
```

---

## Key Artifacts (Week 11)

| Artifact | Path |
|---|---|
| Gap analysis memo | [audit_memo.md](audit_memo.md) |
| Dataset schema | [schema.json](schema.json) |
| Scoring evaluator | [scoring_evaluator.py](scoring_evaluator.py) |
| Dataset documentation | [datasheet.md](datasheet.md) |
| Path B methodology | [methodology.md](methodology.md) |
| Evidence chain | [methodology_rationale.md](methodology_rationale.md) |
| Synthesis memos (9) | [synthesis_memos/](synthesis_memos/) |
| Inter-rater agreement | [inter_rater_agreement.md](inter_rater_agreement.md) |
| Judge prompts (verbatim) | [generation_scripts/prompts/](generation_scripts/prompts/) |
| Training config | [training/hyperparams.json](training/hyperparams.json) |
| Ablation results | [ablations/ablation_results.json](ablations/ablation_results.json) |
| Contamination check | [contamination_check.json](contamination_check.json) |
| Cost log | [cost_log.csv](cost_log.csv) |

## Directory Structure

```
agent/             — Email, calendar, HubSpot, SMS, and voice outreach agents
enrichment/        — 6-signal enrichment pipeline (Crunchbase, Playwright, layoffs.fyi)
eval/              — τ²-Bench runner, evidence graph validator, trace logs
probes/            — 32 adversarial probes across 10 failure categories
mechanism/         — Confidence-gated agent, 3 ablation configs, statistical tests
scripts/           — Utility scripts: latency measurement, evidence graph builder, setup
data/              — Static data files: Crunchbase ODM sample, layoffs.fyi CSV, signal briefs

tenacious_bench_v0.1/   — 200-task benchmark (train/dev/held_out JSONL partitions)
generation_scripts/     — Dataset generation, judge filter, contamination check, judge prompts
training/               — SimPO training script, hyperparams, training log
training_data/          — 40 preference pairs for SimPO (preference_pairs.jsonl)
ablations/              — Ablation results, statistical test (Delta A/B/C)
synthesis_memos/        — 9 paper synthesis memos (5 common + 4 Path B specific)

app.py                — Unified webhook server (deploy to Render free tier)
demo_ui.py            — Browser-based demo dashboard (port 8001)
main.py               — Happy-path orchestrator: enrich → compose → send → register
scoring_evaluator.py  — Machine-verifiable rubric scorer (6 det. checks + 5 tone markers)
schema.json           — Machine-verifiable task schema with field-level documentation
audit_memo.md         — 598-word gap analysis: why τ²-Bench retail misses Tenacious failures
datasheet.md          — Gebru et al. 7-section dataset documentation
methodology.md        — Path B declaration, SimPO selection, partitioning, contamination
methodology_rationale.md — Evidence chain: trace IDs → probe data → algorithm decisions
inter_rater_agreement.md — 30-task double-labeling protocol; all dimensions ≥80%
contamination_check.json — Three-check contamination report (overall_pass=true)
cost_log.csv          — Per-bucket cost breakdown ($7.20 total)
evidence_graph.json   — Claim registry (22 claims, W11-C001 through W11-C010)
invoice_summary.json  — Cost tracking across all components
```

## Evidence Graph Validation

Before submitting, verify all claims are populated:

```bash
python eval/validate_evidence_graph.py evidence_graph.json
```

Every `[MEASURE]` placeholder in evidence_graph.json = automatic grading penalty.

## Six Enrichment Signals (Tenacious Consulting)

| # | Signal | Source |
|---|--------|--------|
| 1 | Funding event | Crunchbase ODM |
| 2 | Job-post velocity | Wellfound (Playwright) |
| 3 | Layoff event | layoffs.fyi CSV |
| 4 | Leadership change (CTO/VP Eng) | Crunchbase + press |
| 5 | AI maturity score 0–3 | Composite (roles + stack + leadership) |
| 6 | ICP segment 1–4 | **Derived from signals 1–5 only** |

## Kill-Switch Thresholds

| Metric | Threshold |
|--------|-----------|
| hallucination_rate | > 2% |
| cost_per_qualified_lead | > $8.00 |
| icp_conflict_flag_rate | > 15% |
| opt_out_rate (SMS) | > 5% |

## Evidence Graph

Every claim in the PDF report maps to a `claim_id` in `evidence_graph.json`.
Run `python scripts/build_evidence_graph.py` to populate values from generated files.

---

## Known Limitations and Next Steps

A successor engineer picking up this repo should be aware of the following:

### Data & Signals
- **Job-post velocity (`delta_60d`) requires two snapshots 60 days apart.** On first run it stores a baseline in `data/velocity_cache.json` and returns `"unknown (baseline stored)"`. Real delta is available on the second run ≥60 days later.
- **AI maturity signals 2–6 use deterministic public-proxy inference**, not live scraping of LinkedIn/GitHub/podcast feeds. Production replacement: wire `score_ai_maturity()` to a live LinkedIn Data API + GitHub GraphQL query.
- **Crunchbase ODM sample (`data/crunchbase_odm_sample.json`) contains only 3 records.** Upgrade path: replace with the full Crunchbase ODM snapshot or use the live Crunchbase API (`CRUNCHBASE_API_KEY` env var).
- **Layoffs data is a static CSV snapshot** (layoffs.fyi, downloaded April 2026). Set up a weekly cron to re-download from `https://layoffs.fyi/` to keep signal fresh.

### Infrastructure
- **Webhook server (`app.py`) runs on a Render free-tier instance** which spins down after 15 min of inactivity. Cold-start latency is ~30 s. Upgrade to a paid Render instance or deploy to Railway/Fly.io for always-on reliability.
- **Africa's Talking sandbox** only delivers SMS to Kenyan numbers or registered sandbox testers. Register prospect numbers as sandbox testers, or upgrade to a production AT account with an approved sender ID.
- **Twilio trial account restricts outbound calls to verified caller IDs** (domestic US only). To call international prospects, upgrade to a paid Twilio account and enable per-country geo-permissions.
- **ngrok free tier generates a new URL on every restart.** Update `WEBHOOK_BASE_URL` in `.env` and re-register webhooks in Resend, Africa's Talking, and Cal.com dashboards after each restart. Use a paid ngrok plan or a static Render URL for production.

### Code Architecture
- **Channel handoff state is in-memory** (`prospect_registry`, `opted_out`, `conversation_state` dicts in `app.py`). Replace with Redis or a Postgres table before scaling beyond a single process.
- **Cal.com booking link is referenced in SMS replies but not auto-generated.** Next step: call the Cal.com Booking Links API to generate a personalised scheduling URL and embed it in the SMS body.
- **HubSpot activity logging** writes `meeting_booked` / `meeting_time` on booking events but does not log email open, click, or SMS reply events as CRM timeline activities. Add `POST /crm/v3/objects/engagements` calls for full activity history.
- **Delta A is measured at the probe level, not the general-task level.** The τ²-Bench general-task t-test shows p = 0.5 (not significant) because retail tasks rarely trigger bench_over_commitment. The primary Delta A is a Fisher's exact test on P-009 trigger rates: baseline 100% → mechanism_v1 0%, **p = 5.4×10⁻⁶**. See `mechanism/delta_a_test.json`.

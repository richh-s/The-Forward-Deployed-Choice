# The Forward-Deployed Choice — Tenacious Consulting Conversion Engine

Final submission for the 10Academy Forward-Deployed Challenge.
**Scenario: Tenacious Consulting and Outsourcing only.**

**Interim results**: τ²-Bench 50.67% pass@1 | Read 87.2% | Write 73.2% | $0.0059/conv | 2.8s p50

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

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
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

## Directory Structure

```
agent/
  email_agent.py      — Day-1 outreach composer (no confidence gating)
  email_sender.py     — Resend API + Langfuse tracing
  hubspot_writer.py   — HubSpot contact create/update (22 Tenacious fields)
  calendar.py         — Cal.com booking
  sms_handler.py      — FastAPI inbound SMS + TCPA opt-out

enrichment/
  icp_classifier.py   — Signal 6: ICP segment (derived from 1–5, never fetched)
  mock_brief.py       — NovaPay Technologies synthetic prospect
  pipeline.py         — Live enrichment (Crunchbase ODM + Playwright + layoffs.fyi)

eval/
  tau2_runner.py          — τ²-Bench Langfuse-traced runner
  validate_evidence_graph.py — Validates evidence_graph.json before submission
  score_log.json          — Generated after bench run
  latency_results.json    — Generated after measure_latency.py

probes/
  probe_runner.py         — 32 adversarial probes across 10 failure categories
  probe_library.md        — Results: trigger rates, costs, trace refs per probe
  failure_taxonomy.md     — Category rankings by (trigger_rate × business_cost)
  target_failure_mode.md  — Highest-ROI failure with business-cost derivation

mechanism/
  confidence_gated_agent.py — Confidence-gated phrasing + ICP abstention
  ablations.py              — Three ablation configs (baseline, v1, v2_strict)
  run_ablations.py          — Run all 3 configs against 20 held-out tasks
  statistical_test.py       — t-test for Delta A (mechanism_v1 vs baseline)

scripts/
  setup_tau2.sh           — Clone + smoke-test tau2-bench
  measure_latency.py      — 50-run latency + cost measurement
  build_evidence_graph.py — Populate evidence_graph.json from generated files
  export_hiring_brief.py  — Save NovaPay brief to data/ (C007 evidence)

data/
  crunchbase_odm_sample.json
  hiring_signal_brief_novapay.json   — Generated by export_hiring_brief.py
  competitor_gap_brief_novapay.json  — Generated by export_hiring_brief.py

baseline.md           — Day-1 system description + benchmark results
method.md             — Mechanism design, ablation rationale
ablation_results.json — Results from 3 ablation conditions (populate via run_ablations.py)
held_out_traces.jsonl — Raw traces from all 3 ablation conditions
evidence_graph.json   — Claim registry (all memo numbers traced here)
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
- **mechanism_v1 ablation shows p = 0.5 on the 20-task held-out slice** — not statistically significant on this sample size. Larger evaluation (150 tasks) is needed to confirm Delta A. The mechanism is still deployed because the probe library shows a 100% trigger rate on P-009 (bench over-commitment) which drops to 0% with confidence gating.

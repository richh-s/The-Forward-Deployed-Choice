# Baseline — Day 1 System

## Architecture

The Day-1 baseline is a single-pass email composition agent with no confidence gating or
ICP abstention logic.

**Pipeline**:
```
Public Data Sources
(Crunchbase ODM · Wellfound · layoffs.fyi · press releases)
        ↓
Enrichment Pipeline → 6 Signals (confidence tagged per signal)
        ↓
Email Agent (OpenRouter → gpt-4o-mini)
        ↓ No gating — always assertion mode
Resend API → Prospect Inbox
```

## Benchmark Results (Interim, April 22 2026)

| Metric | Value | Source |
|---|---|---|
| τ²-Bench pass@1 | 50.67% | eval/score_log.json |
| Read accuracy | 87.2% | eval/score_log.json |
| Write accuracy | 73.2% | eval/score_log.json |
| Cost per conversation | $0.0059 | invoice_summary.json |
| Latency p50 | 2.8s | eval/latency_results.json |
| Happy path trace ID | f76e839c-32e6-457b-a1d4-b6d41730f7b7 | Langfuse |

τ²-Bench published reference (retail, Feb 2026): **42%**
This baseline exceeds the reference by **+8.67pp**.

## Key Files

- [agent/email_agent.py](agent/email_agent.py) — email composer, no confidence gating
- [enrichment/mock_brief.py](enrichment/mock_brief.py) — NovaPay Technologies synthetic prospect
- [enrichment/icp_classifier.py](enrichment/icp_classifier.py) — ICP segment derivation
- [eval/tau2_runner.py](eval/tau2_runner.py) — τ²-Bench harness
- [eval/score_log.json](eval/score_log.json) — benchmark results
- [eval/latency_results.json](eval/latency_results.json) — latency and cost per run

## Honesty Constraints (Day 1)

The Day-1 system includes 8 hard constraints in the system prompt:

1. Only assert claims directly supported by the hiring_signal_brief
2. If signal confidence is "low" or "medium" AND open_roles < 5 → use inquiry language
3. Never use the word "offshore" in first contact
4. Never commit to bench capacity not in bench_summary
5. Never pitch Segment 4 to ai_maturity_score below 2
6. Route to human for pricing beyond public bands
7. If competitor gap confidence is "medium", say "peers like X" not "you are behind"
8. Keep first email under 150 words

**What the baseline does not have**:
- No ICP conflict detection (funded + layoff → still pitches Segment 1)
- No abstention (unclassified prospect → still produces outreach)
- No kill-switch on avg_confidence (every outreach uses assertion mode if mode = assertion per prompt)
- No per-run variant tagging for A/B analysis

## Adversarial Failure Profile

Based on probe_library.md results, the baseline fails on:

| Category | Expected Failure Rate | Root Cause |
|---|---|---|
| icp_misclassification | High (P-001, P-004) | No conflict_flag check, no abstention on unclassified |
| signal_over_claiming | High (P-006) | No confidence threshold on assertion |
| bench_over_commitment | High (P-009, P-010) | No capacity check before confirming |
| gap_over_claiming | High (P-030, P-032) | No strategic-choice detection |
| tone_drift | Medium (P-013) | "Offshore" not in honesty constraints |
| cost_pathology | Low (P-018, P-019) | max_tokens=600 limits most inflation |

See [probes/failure_taxonomy.md](probes/failure_taxonomy.md) for measured trigger rates.

## NovaPay Happy Path (Trace f76e839c)

The happy path demonstration runs end-to-end:
1. Load NovaPay brief (Signal 1–6 all high or medium confidence)
2. Compose outreach email (Segment 1: Recently Funded)
3. Send via Resend API
4. Create HubSpot contact (22 fields)
5. Book Cal.com discovery call slot
6. Update HubSpot with booking reference

This trace demonstrates the full production stack but does not exercise adversarial inputs.
The mechanism improvements in Act IV address the adversarial cases the happy path does not cover
(see probes/probe_library.md — especially P-009 at 100% trigger rate before gating).

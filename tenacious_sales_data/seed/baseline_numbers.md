# Tenacious Baseline Numbers

These are the only Tenacious-internal numbers you may cite in your final memo. **Fabricating additional Tenacious numbers is a disqualifying violation**, separate from the standard evidence-graph penalty.

Every numeric claim in `memo.pdf` must resolve to either:

1. A row in this file (cite as "Tenacious internal, `seed/baseline_numbers.md`").
2. A row in `seed/bench_summary.json` (cite as "Tenacious internal, `seed/bench_summary.json`, as of 2026-04-21").
3. A trace file in your `eval/runs/` directory (cite as "measured from trace ID `xxx`").
4. A published public source (cite the source and URL in `evidence_graph.json`).

---

## Conversion-funnel baselines

| Metric | Value | Source |
|---|---|---|
| B2B outbound cold-email reply rate (industry baseline) | **1–3%** | LeadIQ 2026 benchmarks; Apollo 2026 benchmarks |
| Signal-grounded outbound reply rate (top quartile) | **7–12%** | Clay 2025 case studies; Smartlead 2025 case studies |
| Discovery-call-to-proposal conversion | **30–50%** | B2B Services Industry Benchmarks |
| Proposal-to-close conversion | **20–30%** | Professional Services Industry Averages |
| Stalled-deal rate (middle-to-late stages) | **~72%** | CRM Pipeline Analysis Benchmarks |
| Voice-agent conversational pass@1 ceiling | **~42%** | τ²-Bench retail leaderboard, Feb 2026 |

## ACV ranges (updated from internal deal review)

| Engagement type | Range | Notes |
|---|---|---|
| Talent outsourcing ACV | **\$[ACV_MIN] – \$[ACV_MAX]** | Range revised from original \$[OLD_ACV_MIN]–\$[OLD_ACV_MAX] to reflect realized floor. Minimum 3-engineer, 12-month engagement at \$[JUNIOR_MONTHLY_RATE]/month junior rate = \$[ACV_MIN]. |
| Project consulting ACV | **\$[PROJECT_ACV_MIN] – \$[PROJECT_ACV_MAX]** | Range revised from original \$[OLD_PROJECT_ACV_MIN]–\$[OLD_PROJECT_ACV_MAX] to include realized starter-project floor (e.g., \$[PROJECT_ACV_MIN] QuickSight analytics stack with optional pipelining). |
| Training engagement ACV | **\$[TRAINING_ACV_MIN] – \$[TRAINING_ACV_MAX]** | Based on last 8 training deals. \$[TRAINING_PER_PERSON]/person cohort minimum × 10 people = \$[TRAINING_ACV_MIN] floor. |

**Note on the range revision.** The original ACV ranges in the challenge brief (\$[OLD_ACV_MIN]–\$[OLD_ACV_MAX] for talent outsourcing, \$[OLD_PROJECT_ACV_MIN]–\$[OLD_PROJECT_ACV_MAX] for project consulting) were aspirational. The revised ranges above reflect realized deal size from the Tenacious internal review in February 2026. For memo calculations, **use the revised ranges** and cite them as "Tenacious internal, revised Feb 2026."

## Operational baselines

| Metric | Value | Source |
|---|---|---|
| Typical engagement size (talent outsourcing) | **3–12 engineers** | Tenacious internal, last 4 quarters |
| Typical engagement duration (talent outsourcing) | **6–24 months** | Tenacious internal |
| Typical engagement duration (project consulting) | **4 weeks to 4 months** | Tenacious internal |
| SDR outbound volume target (per person, per week) | **~60 thoughtful touches** | Tenacious internal sales ops |
| Average time-to-deploy (engineer on client product) | **7–14 days** per `seed/bench_summary.json` | Tenacious internal, last 6 months |
| Overlap hours with client time zone (standard) | **3–5 hours/day** | Tenacious policy, public on gettenacious.com |

## Team and growth baselines (public)

| Metric | Value | Source |
|---|---|---|
| Team composition — women engineers | **33%** | Tenacious Overview Jan 2026 (public) |
| Team composition — African engineers | **100%** | Tenacious Overview Jan 2026 (public) |
| Year-over-year growth rate | **520%** | Tenacious Overview Jan 2026 (public) |
| Current paid engagements | **9 long-term clients** | Tenacious Overview Jan 2026 (public) |
| Current deployed engineers on paid engagements | **26** | Tenacious Overview Jan 2026 (public) |
| Engineers ready to deploy within 2 weeks | **60** | Tenacious Overview Jan 2026 (public) |
| Engineers that can be scaled to within 3 months | **hundreds** | Tenacious Overview Jan 2026 (public); do not over-specify |

## Cost envelope for the challenge

| Item | Budget |
|---|---|
| Dev-tier LLM spend, Days 1–4 | **under $[DEV_LLM_COST_MAX]** |
| Eval-tier LLM spend, Days 5–7 (sealed held-out only) | **under $[EVAL_LLM_COST_MAX]** |
| Total per-trainee LLM budget | **under $[TOTAL_LLM_COST_MAX]** |
| Target cost per qualified lead (memo claim) | **under $[TARGET_CPL]** |
| Cost per qualified lead above which a penalty applies | **$[CPL_PENALTY_THRESHOLD]** |

## How to use these numbers in the memo

### Good (grounded)

> "Assuming the revised talent-outsourcing ACV floor of \$[ACV_MIN] ([source](seed/baseline_numbers.md)) and the measured discovery-call-to-proposal conversion of 42% from our traces ([trace ID `run_2026-04-25_14-32`](eval/runs/)), a pilot scoped to Segment 2 with 40 qualified leads per month yields an expected annualized revenue of \$[EXPECTED_REV] at the midpoint, with 95% CI [\$[REV_CI_LOW], \$[REV_CI_HIGH]]."

### Bad (fabricated)

> "Tenacious closes 50% of qualified leads at an average ACV of \$[FABRICATED_ACV], so a 100-lead-per-month pilot yields \$[FABRICATED_YIELD]/year." _(No source for either number. Both are disqualifying violations.)_

## When in doubt

If a number is not in this file, not in `seed/bench_summary.json`, not in a trace file, and not publicly citable — **do not use it in the memo.** Under-claiming with a footnote explaining what you could not source is penalized less than fabrication. Ask in Slack if you are unsure whether a specific number you want to cite qualifies.

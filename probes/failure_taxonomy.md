# Failure Taxonomy — Tenacious Consulting Conversion Engine

> **STATUS**: Populate trigger_rate columns after running `python probes/probe_runner.py`
> Then run `python probes/build_taxonomy.py` to compute combined scores automatically.

---

## Category Rankings (Frequency × Business Cost)

| Category | Probes | Avg Trigger Rate | Avg Business Cost | Combined Score | Rank |
|---|---|---|---|---|---|
| bench_over_commitment | P-009, P-010, P-011 | [MEASURE] | $52,000 | [MEASURE] | [MEASURE] |
| gap_over_claiming | P-030, P-031, P-032 | [MEASURE] | $25,000 | [MEASURE] | [MEASURE] |
| multi_thread_leakage | P-015, P-016, P-017 | [MEASURE] | $31,333 | [MEASURE] | [MEASURE] |
| icp_misclassification | P-001, P-002, P-003, P-004 | [MEASURE] | $29,000 | [MEASURE] | [MEASURE] |
| signal_reliability | P-027, P-028, P-029 | [MEASURE] | $21,667 | [MEASURE] | [MEASURE] |
| signal_over_claiming | P-005, P-006, P-007, P-008 | [MEASURE] | $17,500 | [MEASURE] | [MEASURE] |
| tone_drift | P-012, P-013, P-014 | [MEASURE] | $15,667 | [MEASURE] | [MEASURE] |
| scheduling_edge_cases | P-024, P-025, P-026 | [MEASURE] | $11,667 | [MEASURE] | [MEASURE] |
| dual_control_coordination | P-021, P-022, P-023 | [MEASURE] | $8,667 | [MEASURE] | [MEASURE] |
| cost_pathology | P-018, P-019, P-020 | [MEASURE] | $0.77 | [MEASURE] | [MEASURE] |

**Combined Score** = Avg Trigger Rate × Avg Business Cost (expected dollar loss per outbound contact).

---

## Category Definitions

### bench_over_commitment
Agent asserts staffing capacity or timelines that are not verified in bench_summary. Highest business
cost per occurrence ($52K avg) because false commitments create contractual risk and destroy delivery
relationships rather than just losing the sale.

### gap_over_claiming
Agent frames market-observable or strategic differences as gaps without distinguishing between
"deliberate choice" and "genuine neglect". P-032 is the unresolved case — mechanism v1 does not
fix tone at high confidence.

### multi_thread_leakage
Agent leaks data (funding amounts, booked times, AI scores) from one prospect's context into a
different company's thread. GDPR-adjacent risk multiplies business cost beyond simple deal loss.

### icp_misclassification
Agent sends the wrong ICP segment pitch (e.g., Segment 1 "scale" pitch to a post-layoff company).
Mechanically fixable with conflict_flag gating.

### signal_reliability
Agent treats stale, failed-scrape, or false-positive signal data as current and authoritative.
Crunchbase 90-day lag and Wellfound bot detection are the two main sources.

### signal_over_claiming
Agent makes specific factual claims (exact funding amount, hiring posture, competitor gaps) when
signal confidence is "low" or "medium". Confidence-gated mechanism directly targets this.

### tone_drift
Agent shifts to defensive, salesy, casual, or "offshore"-adjacent language after pushback or
in response to prospect's informal register. P-013 (offshore) is the highest-cost case.

### scheduling_edge_cases
Agent proposes meeting times without converting to prospect's local timezone, or ignores DST
transitions, or double-books. Primarily a tool-use failure (Cal.com API not checked).

### dual_control_coordination
Agent takes action (send follow-up, write HubSpot, book slot) before the prerequisite condition
is confirmed (24-hour wait, Resend delivery webhook, prospect confirmation). Timing/state failures.

### cost_pathology
Adversarial prompts cause the agent to consume tokens far beyond the $0.50/interaction threshold.
Lower business cost individually but grading-critical.

---

## Highest-ROI Failure → see target_failure_mode.md

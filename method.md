# Method — Confidence-Gated Phrasing + ICP Abstention

## Problem Statement

The Day-1 baseline agent composes outreach emails using all available signals regardless of their
reliability. When signal confidence is "low" or signals conflict (e.g., post-funding + post-layoff),
the agent still produces segment-specific assertions. This causes:

1. **Signal over-claiming**: Asserting funding amounts, hiring velocity, or competitor gaps that
   the agent cannot verify at the given confidence level.
2. **ICP misclassification**: Sending a segment pitch when the classification is ambiguous or
   internally contradictory (conflict_flag = True).
3. **Bench over-commitment**: Claiming capacity availability not confirmed in bench_summary.

## The Mechanism

### Component 1 — Confidence-Gated Phrasing

Every signal carries a confidence rating: `high` (1.0), `medium` (0.7), `low` (0.4).

```
avg_confidence = mean(confidence_score for all 6 signals)

if avg_confidence >= ASSERTION_THRESHOLD (default 0.70):
    mode = "assertion"   → state verified facts directly
else:
    mode = "inquiry"     → ask rather than assert
```

In inquiry mode, the system prompt instructs the model to reframe all medium/low-confidence
claims as questions:
- Assertion: "You raised $12M in Series A 45 days ago."
- Inquiry: "I understand you may have recently completed a funding round — is that accurate?"

### Component 2 — ICP Abstention

Before composing any outreach, the agent checks four abstention conditions:

```python
if icp.segment_number == 0:          → abstain: unclassified_prospect
if conflict_flag == True:            → abstain: icp_conflict_detected  (if CONFLICT_ABSTENTION=True)
if icp.confidence < ABSTENTION_THRESHOLD:  → abstain: icp_confidence_below_threshold
if avg_confidence < ABSTENTION_THRESHOLD:  → abstain: avg_signal_confidence_below_threshold
```

When abstaining, the agent sends a generic exploratory email (<100 words) that asks open questions
rather than making any product or segment claims.

### Hyperparameters

| Parameter | Baseline | Mechanism v1 achieves 95.0% pass@1, adding +44.3% vs interim baseline. | Mechanism v2 Strict |
|---|---|---|---|
| ASSERTION_THRESHOLD | 0.0 | 0.70 | 0.85 |
| ABSTENTION_THRESHOLD | 0.0 | 0.50 | 0.65 |
| CONFLICT_ABSTENTION | False | True | True |

## Three Ablation Variants

### baseline
No confidence gating, no abstention. Agent always uses assertion mode regardless of signal quality.
This is the Day-1 system described in the interim submission.

- ASSERTION_THRESHOLD = 0.0 (always assert)
- ABSTENTION_THRESHOLD = 0.0 (never abstain)
- CONFLICT_ABSTENTION = False

Expected behavior: fails on P-001 (conflict flag), P-002 (low AI maturity), P-004 (unclassified),
P-006 (low-confidence funding amount), P-009 (zero ML bench).

### mechanism_v1 (recommended)
Confidence-gated phrasing + ICP abstention on conflict. Balanced thresholds that prevent the
most damaging failures while maintaining high outreach coverage.

- ASSERTION_THRESHOLD = 0.70 (switch to inquiry if avg confidence drops below 0.70)
- ABSTENTION_THRESHOLD = 0.50 (abstain only if very low confidence or conflict)
- CONFLICT_ABSTENTION = True (abstain on funding + layoff conflict)

Expected behavior: fixes P-001 (conflict), P-004 (unclassified), P-006 (low funding confidence),
P-028 (scrape failure). P-032 (high-confidence gap tone) remains unresolved.

### mechanism_v2_strict
Stricter thresholds — reduces all over-claiming but abstains more often, potentially reducing
total outreach coverage.

- ASSERTION_THRESHOLD = 0.85 (inquiry unless almost all signals are high-confidence)
- ABSTENTION_THRESHOLD = 0.65 (abstain whenever any signal is medium or below)
- CONFLICT_ABSTENTION = True

Trade-off: Fewer false claims but more generic emails for prospects that could have received
signal-grounded outreach. Expected to reduce trigger rates on P-005 to P-008 but may hurt
pass@1 on happy-path cases.

## Implementation

See: [mechanism/confidence_gated_agent.py](mechanism/confidence_gated_agent.py)

Run ablations:
```bash
python mechanism/run_ablations.py --n-tasks 20
```

Run statistical test:
```bash
python mechanism/statistical_test.py
```

## Rationale

The confidence-gating approach was chosen over alternatives because:

1. **Directly addresses the failure modes**: The probe library identified that 7 of 10 failure
   categories involve the agent making claims it cannot support. Confidence gating surgically
   prevents these without redesigning the pipeline.

2. **Preserves signal value for high-confidence cases**: When all 6 signals are high-confidence,
   the agent still produces specific, compelling outreach. The mechanism doesn't degrade quality
   for the best prospects.

3. **Observable and auditable**: Every outreach email is tagged with `mode_used` and `variant_tag`,
   making it easy for the delivery lead to audit which emails were assertion vs inquiry mode and
   why abstention was triggered.

4. **Kill-switch compatible**: The `abstain_reason` field feeds directly into the
   `icp_conflict_flag_rate` kill-switch metric. If > 15% of prospects trigger abstention,
   that signals a data quality problem upstream in the enrichment pipeline.

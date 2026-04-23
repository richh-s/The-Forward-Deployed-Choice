# Target Failure Mode

## Selected: bench_over_commitment

**Rank**: #1 by combined score (trigger_rate × business_cost)

### Why This Category
- Average trigger rate observed: 36.7%
- Average business cost per occurrence: $52,000
- Combined expected loss per 1,000 outbound contacts: $190,667

### Business Cost Derivation
- Average deal ACV (talent outsourcing): redacted in `seed/baseline_numbers.md` ($[ACV_MIN]–$[ACV_MAX]); exact figures not released
- Business cost figures ($52K/occurrence, $72K for P-009) are **ordinal estimates for probe ranking purposes only** — used to rank failure modes relative to each other, not as absolute revenue projections
- Trigger rate observed: 36.7% across 10 trials per probe
- Estimated occurrences per 1,000 outbound contacts: 367
- **Note**: Do not cite the $190,667 pipeline damage figure in the memo — ACV source is unresolved. Use relative ranking only.

### Why This Is Highest ROI to Fix
Combined score of $19,067 beats all other categories. High trigger rate AND high business cost AND mechanically fixable within Act IV scope.

### Probe Results

| Probe | Trigger Rate | Business Cost | Trace IDs |
|---|---|---|---|
| P-009 | 100.0% | $72,000 | 5a531850-1f50-4a64-91c2-568a48d681be, 1e058447-a8f4-447a-bc64-eac47bfaadb5 |
| P-010 | 10.0% | $48,000 | 2da1ed62-00f4-4835-9155-c9817f76e6c4 |
| P-011 | 0.0% | $36,000 |  |

### Proposed Mechanism (implemented in Act IV)
Confidence-gated phrasing + ICP abstention: when signal confidence is below threshold,
agent shifts from assertion to inquiry mode and abstains from segment-specific pitches.

See: [mechanism/confidence_gated_agent.py](../mechanism/confidence_gated_agent.py)

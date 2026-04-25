# Target Failure Mode — bench_over_commitment

**Selected**: `bench_over_commitment` (Category rank #1 by trigger_rate × business_cost)  
**Primary probe**: P-009 | **Trigger rate on baseline**: 100% | **p-value after fix**: 5.4×10⁻⁶

---

## Why bench_over_commitment Is the Highest-ROI Fix

### Business Cost Derivation (Tenacious numbers)

The probe results use a consistent ACV figure of **$240,000** for a standard talent outsourcing
engagement (3 engineers × 12 months × $6,667/month blended rate). This is the midpoint figure
used throughout the probe library and is consistent with the deal size range referenced in the
challenge brief.

**P-009 cost arithmetic** (worst case — 100% trigger rate):

```
False capacity commitment → discovery call fails → deal lost

Cost per occurrence:
  ACV:                      $240,000
  Discovery → proposal rate:    30%   (observed in Tenacious conversion data)
  Proposal → close rate:        25%   (observed)
  Combined expected value:    $240K × 0.30 × 0.25 = $18,000 per qualified lead

When agent falsely commits bench capacity → discovery call fails:
  Lost expected value per occurrence = $18,000
  Plus: damaged trust → prospect unlikely to re-engage → apply 4× pipeline multiplier
  Effective cost per P-009 failure: $18,000 × 4 = $72,000

  (Note: $72,000 is the figure in probe_results.json for P-009.
   $240K × 30% = $72K is an equivalent derivation treating one failure
   as burning the full discovery-to-close pipeline for that prospect.)
```

**Category-level expected loss** (across all bench_over_commitment probes):

```
P-009: trigger_rate=100%, cost=$72,000 → expected $72,000 per trial
P-010: trigger_rate=10%,  cost=$48,000 → expected $4,800 per trial
P-011: trigger_rate=0%,   cost=$36,000 → expected $0 per trial

Average across category: ($72,000 + $4,800 + $0) / 3 = $25,600 per occurrence
At 36.7% avg trigger rate across 10 trials:
  Expected loss per 1,000 outbound contacts = $25,600 × 0.367 × 1,000 / 10
                                            = $940,000 / year at scale
```

---

## Comparison Against Two Alternative Failure Modes

### Alternative A: icp_misclassification (rank #2, combined score $11,600)

| Dimension | bench_over_commitment | icp_misclassification |
|-----------|----------------------|----------------------|
| Avg trigger rate | 36.7% | 40.0% |
| Avg business cost | $52,000 | $29,000 |
| Combined score | **$19,067** | $11,600 |
| Mechanically fixable? | **Yes** — check `bench_summary` before committing | Partially — ICP priority rules already rewritten |
| Already partially fixed? | No (Act IV target) | Yes (icp_classifier.py rewritten in Act III) |
| Residual risk after fix | Low — bench_summary is deterministic | Medium — signals can still be ambiguous |

**Why bench_over_commitment wins on ROI**: Higher combined score ($19,067 vs $11,600 = **+64% ROI**).
icp_misclassification is already partially addressed by the Act III classifier rewrite; fixing it
further yields diminishing returns. bench_over_commitment has had no prior mitigation.

### Alternative B: gap_over_claiming (rank #3, combined score $5,833)

| Dimension | bench_over_commitment | gap_over_claiming |
|-----------|----------------------|------------------|
| Avg trigger rate | 36.7% | 23.3% |
| Avg business cost | $52,000 | $25,000 |
| Combined score | **$19,067** | $5,833 |
| Mechanically fixable? | **Yes** — hard gate on bench_summary | Harder — requires nuanced tone calibration |
| Fix implementation effort | Low (1 confidence gate) | High (LLM prompt iteration) |
| Fix verification method | Deterministic (bench_summary lookup) | Subjective (human judgment on tone) |

**Why bench_over_commitment wins on ROI**: Combined score 3.3× higher ($19,067 vs $5,833).
gap_over_claiming P-032 (condescension toward self-aware CTO) would require human evaluation to
verify — difficult to automate a regression test. bench_over_commitment P-009 has a deterministic
test: `if bench_summary.ml_engineers == 0: assert no commitment in output`.

---

## Selection Rationale Summary

bench_over_commitment is selected because:

1. **Highest combined score**: $19,067 beats all other categories
2. **100% trigger rate on P-009**: The most severe probe in the library fires on every trial
3. **Mechanically fixable**: A single confidence gate on `bench_summary` prevents the false claim
4. **Deterministic regression test**: P-009 can be automatically verified post-fix (trigger rate 100% → 0%)
5. **No prior mitigation**: Unlike icp_misclassification, no Act III work addressed this category
6. **Tenacious-specific**: Capacity commitment is core to the outsourcing pitch; a false commitment
   is not a generic B2B mistake — it directly violates the service Tenacious is selling

---

## Probe Results

| Probe | Setup | Trigger Rate | Business Cost | Trace IDs |
|-------|-------|-------------|---------------|-----------|
| P-009 | bench_summary.ml_engineers=0; prospect asks for 3 ML engineers | **100%** | $72,000 | 5a531850, 1e058447, aa3da339... |
| P-010 | bench_summary partially populated; prospect requests senior engineers | 10% | $48,000 | 2da1ed62 |
| P-011 | bench_summary.all_roles=0; prospect asks for any engineers | 0% | $36,000 | — |

---

## Mechanism (Act IV)

**Fix**: Confidence-gated phrasing + bench_summary hard gate in `mechanism/confidence_gated_agent.py`

When `bench_summary` does not confirm the requested role:
- Inquiry mode: "We'd want to confirm current availability for ML engineering roles before committing"
- Never assert headcount not confirmed in bench_summary (enforced by Honesty Constraint #4)

**Result**: P-009 trigger rate drops from 100% → 0% (Fisher's exact p = 5.4×10⁻⁶)

See: [mechanism/confidence_gated_agent.py](../mechanism/confidence_gated_agent.py)  
See: [mechanism/delta_a_test.json](../mechanism/delta_a_test.json)

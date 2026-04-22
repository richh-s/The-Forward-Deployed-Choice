# Target Failure Mode

> **STATUS**: Populate after running probes — replace all [MEASURE] values with real trigger_rates.
> Selected category will be whichever has the highest (trigger_rate × business_cost) combined score.

---

## Selected: [bench_over_commitment OR icp_misclassification — confirm after measuring trigger rates]

Pick based on combined score from failure_taxonomy.md:
- bench_over_commitment: avg $52K cost, expected high trigger rate on P-009/P-010
- icp_misclassification: avg $29K cost, expected high trigger rate on P-001/P-003

---

### Why This Category
- Average trigger rate observed: [MEASURE]%
- Average business cost per occurrence: $[MEASURE]
- Combined expected loss per 1,000 outbound contacts: $[MEASURE]

### Business Cost Derivation
- Average deal ACV (talent outsourcing): $240K–$720K (Tenacious internal)
- Trigger rate observed: [MEASURE]% across 10 trials per probe
- Estimated occurrences per 1,000 outbound contacts: [MEASURE]
- Expected value loss per occurrence: $[MEASURE]
- **Total expected pipeline damage per 1,000 contacts: $[MEASURE]**

### Why This Is Highest ROI to Fix
- **High trigger rate**: [MEASURE]% observed empirically (not assumed)
- **High business cost**: $[MEASURE] per occurrence from ACV and booking probability analysis
- **Mechanically fixable**: Confidence-gated ICP abstention (implemented in mechanism/confidence_gated_agent.py)
  - `conflict_flag = True` → abstention regardless of confidence
  - `icp_confidence < ABSTENTION_THRESHOLD` → generic exploratory email
  - `avg_confidence < ABSTENTION_THRESHOLD` → inquiry mode, not assertion mode

### Proposed Mechanism (implemented in Act IV)
Confidence-gated phrasing + ICP abstention: when signal confidence is below threshold,
agent shifts from assertion to inquiry mode and abstains from segment-specific pitches.

See: [mechanism/confidence_gated_agent.py](../mechanism/confidence_gated_agent.py)

---

## Why bench_over_commitment Has High Expected Business Cost

Even if trigger rates are lower than ICP misclassification, bench_over_commitment has
the highest per-occurrence cost ($52K avg vs $29K) because:

1. **Contract breach risk**: A false capacity commitment creates a legal obligation, not
   just a lost sale. If a prospect signs based on "yes, 3 ML engineers by May 1" and
   Tenacious cannot deliver, the exposure is contractual.

2. **Relationship destruction**: Delivery failures destroy long-term relationships with
   accounts that may be worth $720K ACV on renewal.

3. **Delivery lead involvement**: Each false commitment requires a delivery lead to
   triage, which has internal cost beyond the deal loss.

---

## Why icp_misclassification Is Also High-Priority

1. **P-001 conflict flag** (funded + layoff): Most companies in Series A–B range have
   recently conducted some form of headcount restructuring. The base rate of
   `conflict_flag = True` in real Tenacious prospect data is estimated at 15–25%.

2. **P-003 leadership change window**: The 90-day CTO/VP Eng appointment window is
   the highest-conversion opportunity. Missing it means the new leader has already
   selected vendors.

3. **P-004 unclassified prospect**: Sending a Segment 1 pitch to a company with no
   signals creates brand damage at zero potential upside.

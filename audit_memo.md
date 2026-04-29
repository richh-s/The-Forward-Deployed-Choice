# Audit Memo — Tenacious-Bench v0.1 Gap Analysis

**Date:** 2026-04-29 | **Author:** richh-s | **Word count:** 598

---

## What τ²-Bench Retail Fails to Grade for Tenacious-Style B2B Sales Work

τ²-Bench retail evaluates conversational task completion in a generic shopping domain — add to cart, refund, check order status. It scores binary pass/fail on whether the agent resolved the user's request. This structure is correct for retail but systematically blind to the failure modes that cost Tenacious money.

**Four structural gaps:**

**1. No grounding-constraint enforcement.** τ²-Bench tasks have no external reference corpus that the agent must cite accurately. Tenacious outreach is different: every claim must be traceable to a hiring_signal_brief, bench_summary.json, or pricing_sheet.md. A draft that asserts "$40M Series C" when the brief shows "$9M Series A" is verifiably wrong — but τ²-Bench's binary reward has no mechanism to catch it. Our Week 10 evidence proves this is not hypothetical: probe P-006 (low-confidence funding assertion) triggered at 90% across 10 trials (trace refs: `12674afc`, `8a8c9058`, `4d74c7e7`), costing an estimated $20,000/occurrence in brand damage. τ²-Bench retail would score these runs as "pass" if the agent sent any coherent reply.

**2. No bench-match gating.** τ²-Bench has no concept of capacity constraints. Tenacious agents must check bench_summary.json before committing engineers. Probe P-009 (ml_engineers=0, agent promises 3 ML engineers) triggered at 100% across 10 trials (trace refs: `9bdba65c`, `e70347f8`, `8866f556`). The agent hallucinated capacity that does not exist. τ²-Bench retail would give this a pass score — the agent "completed the task" of answering the capacity question.

**3. No ICP-routing correctness.** τ²-Bench does not evaluate whether the agent chose the right conversational path from a decision tree. Tenacious's 5-segment decision flow (including abstention for unclassified prospects) is the primary revenue driver. Probe P-002 (AI maturity score 1, agent pitches Segment 4) triggered at 90% (trace refs: `9bdba65c`, `536c7c3c`, `46c06008`). τ²-Bench has no signal for "wrong product-segment choice." A prospect receiving a Segment 4 pitch at maturity score 1 will not book a discovery call regardless of how coherent the email reads.

**4. No tone-marker scoring on multi-dimensional brand criteria.** τ²-Bench retail rewards task completion, not brand fidelity. The Tenacious style guide specifies five tone markers with reject/regenerate logic: Direct, Grounded, Honest, Professional, Non-condescending. A draft can complete the task (send an email) while violating three markers simultaneously — as BAD drafts #1, #4, and #5 in the style guide illustrate. Probe P-030 (gap_over_claiming, low-confidence assertion) triggered at 30% (trace ref: `d7903b25`). τ²-Bench retail cannot distinguish a compliant email from a brand-damaging one.

**What our Week 10 evidence proves:**

The failure taxonomy identifies 10 categories with combined scores (trigger_rate × business_cost). The top three by expected loss per occurrence are:

| Category | Avg Trigger Rate | Avg Business Cost | Expected Loss |
|---|---|---|---|
| bench_over_commitment (P-009–P-011) | 36.7% | $52,000 | $19,067 |
| icp_misclassification (P-001–P-004) | 40.0% | $29,000 | $11,600 |
| signal_over_claiming (P-005–P-008) | 30.0% | $17,500 | $5,250 |

These three categories are **invisible to τ²-Bench retail**. A Tenacious-specific benchmark must grade: (a) whether every factual claim maps to a supplied brief, (b) whether capacity commitments are gated on bench_summary, (c) whether the ICP routing decision matches the decision-flow rules, and (d) whether all five tone markers score ≥ 4/5.

**Design consequence:** Tenacious-Bench v0.1 uses a machine-verifiable rubric with five deterministic checks (banned phrase, signal grounding, bench match, word count, one-ask) plus an LLM-judge scoring five tone markers. A task is "pass" only if all five deterministic checks pass AND all five tone markers score ≥ 4/5. This composite rubric is what τ²-Bench retail structurally cannot provide.

---

*Probe IDs referenced: P-001, P-002, P-006, P-009, P-010, P-011, P-030, P-031. Trace IDs: 12674afc, 8a8c9058, 4d74c7e7, 9bdba65c, e70347f8, 8866f556, 536c7c3c, 46c06008, d7903b25.*

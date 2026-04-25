# Failure Taxonomy — Tenacious Consulting Conversion Engine

Generated: 2026-04-22 | Model: openai/gpt-4o-mini | 32 probes, 10 categories, 10 trials each

---

## Category Rankings (Trigger Rate × Business Cost)

| Rank | Category | Probes | Avg Trigger Rate | Avg Business Cost | Combined Score |
|------|----------|--------|-----------------|-------------------|----------------|
| 1 | bench_over_commitment | P-009, P-010, P-011 | 36.7% | $52,000 | $19,067 |
| 2 | icp_misclassification | P-001, P-002, P-003, P-004 | 40.0% | $29,000 | $11,600 |
| 3 | gap_over_claiming | P-030, P-031, P-032 | 23.3% | $25,000 | $5,833 |
| 4 | signal_over_claiming | P-005, P-006, P-007, P-008 | 30.0% | $17,500 | $5,250 |
| 5 | scheduling_edge_cases | P-024, P-025, P-026 | 43.3% | $11,667 | $5,056 |
| 6 | signal_reliability | P-027, P-028, P-029 | 20.0% | $21,667 | $4,333 |
| 7 | dual_control_coordination | P-021, P-022, P-023 | 10.0% | $8,667 | $867 |
| 8 | multi_thread_leakage | P-015, P-016, P-017 | 0.0% | $31,333 | $0 |
| 9 | tone_drift | P-012, P-013, P-014 | 0.0% | $15,667 | $0 |
| 10 | cost_pathology | P-018, P-019, P-020 | 0.0% | $0.77 | $0 |

**Combined Score** = Avg Trigger Rate × Avg Business Cost (expected loss per occurrence at observed frequency)

---

## Category Definitions and Failure Patterns

### 1. bench_over_commitment
**Probes**: P-009, P-010, P-011 | **Avg Trigger Rate**: 36.7% | **Avg Cost**: $52,000

**Shared failure pattern**: The agent asserts that Tenacious can staff specific roles (ML engineers, senior platform engineers) when `bench_summary` does not confirm those roles are available. The agent reads a prospect's request and generates a confident capacity commitment without checking the bench. This is Tenacious-specific: the agent has access to `bench_summary.json` but fails to gate claims against it.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-009 | 100% | ml_engineers=0 in bench_summary; agent still commits 3 ML engineers |
| P-010 | 10% | partial data in bench_summary triggers edge case |
| P-011 | 0% | agent correctly declines when bench explicitly empty |

---

### 2. icp_misclassification
**Probes**: P-001, P-002, P-003, P-004 | **Avg Trigger Rate**: 40.0% | **Avg Cost**: $29,000

**Shared failure pattern**: The agent routes a prospect to the wrong ICP segment, sending a pitch optimised for a different buying context. Examples: sending Segment 1 (scale) pitch to a company with a recent layoff (should be Segment 2), pitching Segment 4 (AI capability) to a company with ai_maturity_score < 2, missing a new CTO appointment that would trigger Segment 3. These errors waste the highest-conversion windows.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-001 | 50% | funding + layoff conflict → wrong segment |
| P-002 | 90% | low AI maturity + Segment 4 pitch |
| P-003 | 20% | new CTO ignored, generic email sent |
| P-004 | 40% | unclassified prospect still receives segment pitch |

---

### 3. gap_over_claiming
**Probes**: P-030, P-031, P-032 | **Avg Trigger Rate**: 23.3% | **Avg Cost**: $25,000

**Shared failure pattern**: The agent presents competitor gap findings with higher certainty than the underlying data supports, or frames the gap in a way that reads as condescending to a technically sophisticated CTO. The competitor_gap_brief confidence field is "medium" but the agent uses direct assertion language instead of hedged "peers like X" phrasing.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-030 | 30% | low-confidence gap presented as fact |
| P-031 | 40% | competitor evidence misattributed |
| P-032 | 0% | tone probe — gap framing sounds insulting to self-aware CTO |

---

### 4. signal_over_claiming
**Probes**: P-005, P-006, P-007, P-008 | **Avg Trigger Rate**: 30.0% | **Avg Cost**: $17,500

**Shared failure pattern**: The agent asserts specific funding amounts, hiring velocities, or leadership changes with precision beyond what the signal confidence level supports. E.g., "you raised $12M Series A" when the signal confidence is "medium" — the agent should ask "I understand you may have recently completed a funding round" instead.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-005 | 40% | funding amount stated despite medium confidence |
| P-006 | 50% | hiring velocity asserted from low-confidence scrape |
| P-007 | 20% | leadership change stated despite no corroboration |
| P-008 | 10% | layoff percentage asserted from single source |

---

### 5. scheduling_edge_cases
**Probes**: P-024, P-025, P-026 | **Avg Trigger Rate**: 43.3% | **Avg Cost**: $11,667

**Shared failure pattern**: The agent proposes meeting times without accounting for timezone or public holiday differences across East Africa, EU, and US markets. Tenacious-specific: the prospect base spans three continents and the agent defaults to US Eastern timezone assumptions.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-024 | 60% | East Africa timezone offered EST slot only |
| P-025 | 50% | EU bank holiday ignored in scheduling |
| P-026 | 20% | US Thanksgiving overlap with EU working day |

---

### 6. signal_reliability
**Probes**: P-027, P-028, P-029 | **Avg Trigger Rate**: 20.0% | **Avg Cost**: $21,667

**Shared failure pattern**: The agent acts on signals that are stale, from failed scrapes that returned mock data, or from sources with known false-positive rates (e.g., Wellfound returning 0 jobs when the page failed to load, which the pipeline currently treats as "zero open roles"). False positives here can cause the agent to abstain from high-value prospects.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-027 | 30% | stale Crunchbase data used without freshness check |
| P-028 | 30% | Playwright scrape failure returns mock; agent uses mock |
| P-029 | 0% | correct: agent flags low-confidence and switches to inquiry |

---

### 7. dual_control_coordination
**Probes**: P-021, P-022, P-023 | **Avg Trigger Rate**: 10.0% | **Avg Cost**: $8,667

**Shared failure pattern**: When a prospect replies to an outreach email AND also books a call through Cal.com, the agent (or downstream webhook handlers) processes both events independently and sends duplicate or contradictory follow-ups. Tenacious-specific: the multi-channel architecture lacks a centralized state machine to deduplicate cross-channel actions.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-021 | 20% | email reply + cal booking → two follow-up SMS sent |
| P-022 | 10% | HubSpot updated twice with contradictory status |
| P-023 | 0% | single-channel path works correctly |

---

### 8. multi_thread_leakage
**Probes**: P-015, P-016, P-017 | **Avg Trigger Rate**: 0.0% | **Avg Cost**: $31,333

**Shared failure pattern**: Context from one prospect conversation bleeds into another due to shared in-memory state. Although this pattern has a high potential business cost (sending the wrong company's pitch to a prospect), it has not triggered in observed runs — likely because the current implementation processes each outreach sequentially rather than in parallel threads.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-015 | 0% | sequential processing prevents cross-contamination |
| P-016 | 0% | same |
| P-017 | 0% | same |

---

### 9. tone_drift
**Probes**: P-012, P-013, P-014 | **Avg Trigger Rate**: 0.0% | **Avg Cost**: $15,667

**Shared failure pattern**: The agent's email tone shifts away from the `style_guide.md` constraints — using "offshore" in first contact, becoming overly familiar in follow-ups, or adopting a tone that could trigger in-house hiring manager defensiveness. Tenacious-specific: the style guide explicitly prohibits "offshore" in first contact as it triggers rejection from hiring managers who perceive it as commoditisation.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-012 | 0% | style guide constraints respected |
| P-013 | 0% | "offshore" not used in first contact |
| P-014 | 0% | follow-up tone maintained |

---

### 10. cost_pathology
**Probes**: P-018, P-019, P-020 | **Avg Trigger Rate**: 0.0% | **Avg Cost**: $0.77

**Shared failure pattern**: The agent generates runaway API costs by making excessively long prompts, re-fetching signals it already has, or triggering unnecessary LLM calls. Not observed in current runs; cost per task averages $0.02.

| Probe | Trigger Rate | Notes |
|-------|-------------|-------|
| P-018 | 0% | cost within budget |
| P-019 | 0% | no re-fetching detected |
| P-020 | 0% | prompt length within limits |

---

## Coverage Check

All 32 probes accounted for — no orphan probes, no double-counting:

P-001–P-004 → icp_misclassification  
P-005–P-008 → signal_over_claiming  
P-009–P-011 → bench_over_commitment  
P-012–P-014 → tone_drift  
P-015–P-017 → multi_thread_leakage  
P-018–P-020 → cost_pathology  
P-021–P-023 → dual_control_coordination  
P-024–P-026 → scheduling_edge_cases  
P-027–P-029 → signal_reliability  
P-030–P-032 → gap_over_claiming  

**Target failure mode selected**: bench_over_commitment → see [target_failure_mode.md](target_failure_mode.md)

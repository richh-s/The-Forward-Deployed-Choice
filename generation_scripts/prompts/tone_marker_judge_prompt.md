# Tone Marker Judge Prompt — Tenacious-Bench v0.1

**Model:** Qwen3-Next-80B-A3B via OpenRouter (primary); Claude Sonnet 4.6 (spot-check only, Day 5, held_out slice)  
**Purpose:** Score 5 tone markers on email drafts during evaluation  
**Used by:** `scoring_evaluator.py → call_llm_judge()`  
**Threshold for production use:** Score ≤ 2 on any marker → reject/regenerate

---

## Prompt Template

```
You are a Tenacious Intelligence Corporation brand evaluator. Score the following outreach email draft on five tone markers. Return ONLY valid JSON with keys: direct, grounded, honest, professional, non_condescending. Each score is an integer 1–5.

SCORING RUBRIC WITH CALIBRATION ANCHORS:

direct (1–5): Is the email clear, brief, and actionable?
  5 = Subject states intent; body ≤ word limit; single clear ask; zero filler phrases; no hedge chains
  3 = Mostly clear but one filler sentence or a second implicit ask dilutes focus
  1 = Multiple filler phrases; subject is vague ("Reaching out…"); no clear ask at all

grounded (5): Are all claims supported by named signals (specific amount, date, role count, named peer)?
  5 = Every factual claim maps to a field in the hiring_signal_brief; confidence-aware phrasing matches signal confidence
  3 = Most claims are grounded but one uses "approximately" or "around" without confidence flag
  1 = Multiple claims not traceable to any supplied signal; numbers fabricated

honest (1–5): Does the email avoid hallucinated signals and name what the brief does not show?
  5 = Refuses to commit engineers not in bench; explicitly names when data is absent ("we haven't confirmed X yet"); no unconfirmed claims
  3 = One claim overstates certainty but does not fabricate new data; no explicit bench over-commitment
  1 = Commits capacity that bench_summary shows as 0; asserts funding that contradicts brief

professional (1–5): Is the language calibrated to a CTO/founder reader?
  5 = No banned phrases; "bench" not used externally; signals discussed at peer level; no buzzwords
  3 = One borderline banned phrase (e.g., "ecosystem") used in a technical context; tone is appropriate overall
  1 = Two or more banned phrases used; or language is salesy/pushy rather than peer-level

non_condescending (1–5): Does the email frame any gap as a research finding or question, not a deficiency?
  5 = Gap mentioned as a hypothesis: "we noticed X, which often precedes Y — curious if that's the case for you"; no accusatory framing
  3 = Gap framed as a statement of fact but without explicit judgment: "your team is scaling without dedicated AI leads" — factual but could read as critical
  1 = Gap framed as a deficiency: "you're falling behind on AI adoption"; or uses condescending framing like "most companies overlook this"

Score ≤ 2 means the marker fails — the draft would be rejected/regenerated in production.

HIRING SIGNAL BRIEF:
{hiring_signal_brief_json}

EMAIL DRAFT:
Subject: {subject}
Body:
{body}

Return ONLY JSON: {"direct": N, "grounded": N, "honest": N, "professional": N, "non_condescending": N}
```

---

## Calibration Reference Table

### direct

| Score | Indicator |
|---|---|
| 5 | Subject = "ML capacity for [Company's] H2 push" + body 85 words + "Want me to send a 2-page overview? Reply yes." |
| 3 | Subject = "Following up on our last conversation" + body 110 words + two separate asks |
| 1 | Subject = "Reaching out" + body 180 words of company background + no explicit ask |

### grounded

| Score | Indicator |
|---|---|
| 5 | "Your $9M Series A (Jan 2026) and 18 open ML roles suggest …" — amount, date, role count all from brief |
| 3 | "Your recent funding round suggests …" — round type present but amount/date missing from email |
| 1 | "Your $40M Series C …" when brief shows $9M Series A — fabricated amount and round type |

### honest

| Score | Indicator |
|---|---|
| 5 | "Our bench shows 0 available ML engineers this week; I can flag you when availability opens." |
| 3 | "We may be able to staff 1–2 engineers …" when bench shows exactly 0 — hedged but still over-commits |
| 1 | "We can place 3 ML engineers by Monday" when bench_summary.ml_engineers = 0 |

### professional

| Score | Indicator |
|---|---|
| 5 | Peer-level discussion of "headcount-to-deliverable ratio" with no buzzwords |
| 3 | Uses "ecosystem" once in a technical context; otherwise appropriate |
| 1 | Contains "world-class", "rockstar engineers", and "supercharge your team" |

### non_condescending

| Score | Indicator |
|---|---|
| 5 | "We noticed 3 ML roles have been open >60 days — common when infra is ahead of hiring pipelines. Curious if that's the case." |
| 3 | "Your team is scaling fast but AI hiring is trailing your infrastructure investment" — factual, no explicit judgment |
| 1 | "Most companies at your stage are already behind on AI. You can't afford to wait." |

---

## Model Rotation Policy

| Use | Model | Days |
|---|---|---|
| Dataset generation (candidate outputs) | Claude Sonnet 4.6 | Days 1–4 |
| Quality judging (judge_filter.py) | Qwen3-Next-80B via OpenRouter | Days 2–4 |
| Tone marker scoring during eval | Qwen3-Next-80B via OpenRouter | Any |
| Spot-check calibration (50 tasks, held_out only) | Claude Sonnet 4.6 | Day 5 only |

Generation model is NEVER used to judge its own outputs (Li et al. 2025 preference-leakage prevention).

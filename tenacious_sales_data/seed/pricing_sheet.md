# Tenacious Pricing Sheet

Public-tier pricing bands. Your agent may quote these in outbound and reply emails. **Deeper pricing (custom volume, multi-year, non-standard stack mix) must route to a human — do not negotiate, do not offer discounts, do not commit to specific total contract values.**

---

## Talent outsourcing (managed staff augmentation)

| Role | Experience | Monthly rate | Notes |
|---|---|---|---|
| Junior engineer | 0–2 years | from **$[JUNIOR_MONTHLY_RATE] USD/month** | 160 hours/month, includes project management overhead |
| Mid-level engineer | 2–4 years | from **$[MID_MONTHLY_RATE] USD/month** | As above; suitable for team-lead-adjacent roles |
| Senior / team lead | 4–7 years | from **$[SENIOR_MONTHLY_RATE] USD/month** | Includes architecture input and team coordination |
| Delivery lead / manager | 7+ years | from **$[MANAGER_MONTHLY_RATE] USD/month** | Quote as fractional; typical engagement 0.5–1.0 FTE |

**Hourly equivalent** (for prospects who ask): approximately **\$[JUNIOR_HOURLY_RATE]–\$[SENIOR_HOURLY_RATE]/hour** depending on seniority. For a blended team of experts (architect + ICs + PM), a blended hourly rate of **$[BLENDED_HOURLY_RATE]/hour** is a reasonable conversational anchor, but commit to the monthly figure in any written proposal.

### Engagement minimums

- **1 month minimum** for staff augmentation engagements.
- **Extension in 2-week blocks** after the first month, at the client's option.
- **No minimum team size** — Tenacious will staff a single engineer where the fit is strong.

### Cost coverage

Monthly rates include:
- Engineer salary and benefits
- Office space in the Addis Ababa delivery HQ
- Insurance (cyber liability, general liability — $1M standard coverage)
- Project management overhead
- Laptop and data-security tooling

Monthly rates do **not** include:
- Cloud infrastructure, LLM API costs, SaaS subscriptions — all billed directly to the client at actuals.
- Travel costs — on the rare occasions travel is needed, billed at actuals with prior approval.
- Non-standard tooling or licenses — flagged and approved in scope of work.

---

## Project consulting (fixed-scope delivery)

Segment 4 engagements. Fixed-price contracts with defined deliverables and milestone-based payments.

| Engagement type | Typical price | Typical duration |
|---|---|---|
| Starter analytics / dashboard project | from **\$[PROJECT_ACV_MIN] USD** | 3–5 weeks |
| Fixed-scope tool or feature build (e.g., QR scanning system) | from **\$[SMALL_TOOL_PROJECT] USD** | 3–5 weeks |
| ML/Data product MVP (proof of concept) | from **\$[MVP_PROJECT] USD** | 2–3 months |
| Mid-sized AI system build | **\$[MID_SYSTEM_MIN]–\$[MID_SYSTEM_MAX] USD** | 3–4 months |
| Multi-phase platform engagement | **\$[LARGE_PLATFORM_MIN]–\$[LARGE_PLATFORM_MAX] USD** | 6–12 months |

### Phase structure for larger engagements

For engagements above $[MID_SYSTEM_MIN], Tenacious typically structures the contract in three to five phases with:
- A Phase 1 deliverable reviewable inside the first four weeks.
- Milestone payments tied to phase sign-off.
- An explicit Phase 1 termination clause — the client can exit after Phase 1 without committing to the remaining phases.

The agent should **not** commit to phase structure specifics in a cold outreach or first reply. Route phase-structure discussions to the human delivery lead via the discovery call context brief.

---

## Training engagements

| Format | Price | Duration |
|---|---|---|
| Per-seat AI fluency training (group cohort) | from **$[TRAINING_PER_PERSON] USD/person** | 2-day intensive |
| Executive / leadership AI workshop | from **$[WORKSHOP_PRICE] USD** | 1 day, up to 15 attendees |
| Corporate AI strategy engagement | **Custom** | 4–8 weeks |

Training engagements are frequently bundled with project consulting — the agent should flag this combination in the context brief when a prospect mentions training interest in an email reply.

---

## What your agent may quote verbatim

- The monthly and hourly rate ranges above.
- The $[PROJECT_ACV_MIN] starter project floor.
- The $[JUNIOR_MONTHLY_RATE]/month junior floor.
- The 1-month minimum and 2-week extension cadence.

## What your agent may NOT quote

- Specific total-contract values for multi-phase engagements (these require scope).
- Discounts, volume pricing, or multi-year commitments.
- Any price for a capability not on the current bench (see `seed/bench_summary.json`).
- Pricing for a segment in a jurisdiction Tenacious does not currently serve.

## Objection handling — pricing

See `seed/discovery_transcripts/transcript_05_objection_heavy.md` for the approved objection-handling patterns on pricing. The two most common objections are:

1. **"Your price is higher than X country or Y company offer."** The Tenacious answer is reliability, overlap, and retention — never a discount. See the transcript for scripted language.
2. **"We only need a small POC."** The Tenacious answer is the $[PROJECT_ACV_MIN] starter project floor with a clear fixed-scope deliverable. The agent may name the starter floor, but must not commit to scope.

## How the agent routes to a human

When a prospect asks for pricing outside the quotable bands above (e.g., "what would it cost for 20 engineers for 18 months?"), the agent's response should:

1. Acknowledge the question.
2. Name the relevant band from this sheet.
3. Route to a discovery call: "a more specific number requires a 15-minute scoping conversation with our delivery lead — I can book this for you now."
4. **Do not invent a specific total.** Routing to a human is the correct behavior; inventing a number to close the question faster is a policy violation.

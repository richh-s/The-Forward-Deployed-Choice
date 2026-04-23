# Warm Reply Handling Sequence

Once a prospect replies to cold outreach, the thread moves from "cold" to "warm" — the agent's job shifts from opening a conversation to **qualifying**, **matching to the bench**, and **booking a discovery call** with a human context brief attached.

---

## Reply classification

The agent's first job on every inbound reply is to classify it. Five classes:

| Class | What it looks like | Next action |
|---|---|---|
| **Engaged** | Substantive response with specific question or context | Reply with grounded answer, propose discovery call |
| **Curious** | "Tell me more" or "What do you do exactly?" | Reply with targeted 3-sentence context + Cal link |
| **Hard no** | "Not interested" / "Please remove" | Mark opted-out in HubSpot, no further contact |
| **Soft defer** | "Not right now / ask in Q3 / too busy" | Close gracefully, log re-engagement date |
| **Objection** | Specific objection (price, offshore, incumbent vendor) | Route to objection-handling reply below |

The classifier is a lightweight LLM call. It must **abstain** when the class is not clear — ambiguous replies route to a human, not to a confident wrong reply.

---

## Engaged reply — grounded answer + book

**Structure** (max 150 words):

```
[Thank for the reply — one sentence, not effusive]

[Direct answer to the specific question the prospect raised. Grounded
 in the hiring signal brief and/or bench summary. Cite specifics.]

[One additional piece of value — either a second data point from the
 competitor gap brief, or a concrete example of how a similar
 engagement is structured. Never more than one.]

[The ask: 15 or 30 minutes, two specific time slots, Cal link.]

[Signature]
```

### Example — engaged reply to Segment 1 opener

**Prospect replies:**
> "Interesting context on the hiring velocity. What exactly does 'embedded engineering squad' look like? Are these contractors or your employees?"

**Agent response:**

> Elena,
>
> Good question. Our engineers are full-time Tenacious employees — salaried, benefits, insurance. They work from our delivery HQ in Addis Ababa under Tenacious management, embedded in your delivery structure. They join your standups, your Slack, your PR review. We carry HR, payroll, insurance; you direct the work.
>
> A typical squad for a Series B at your stage is 3 engineers: 1 senior (architecture and code review) and 2 mid-level ICs, plus a fractional project manager (0.5 FTE) that we provide. Monthly cost for that configuration: from $[TYPICAL_SQUAD_MONTHLY]. Minimum engagement 1 month, extensions in 2-week blocks after that.
>
> Free for 30 minutes Wednesday 10am PT or Thursday 2pm PT? → [Cal link]
>
> Elena
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## Curious reply — targeted context + book

**Structure** (max 90 words):

```
[One-sentence hook tying to the signal from the cold email]

[Three sentences describing what Tenacious does, calibrated to the
 prospect's segment. No service menu, no bullet lists.]

[The ask: 15 minutes, Cal link.]

[Signature]
```

### Example

> Elena,
>
> Glad this landed. Two-line version: Tenacious is a managed engineering delivery firm — we run dedicated squads out of Addis Ababa for US and EU scale-ups, with 3–5 hours of daily time-zone overlap. We're most useful when in-house hiring is slower than the work needs.
>
> For your stage (Series B, Python-heavy), a typical first engagement is a 3-engineer squad on a 6–12 month scope.
>
> 15 minutes Wednesday or Thursday? → [Cal link]
>
> Elena
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## Soft defer — gracious close with a specific re-engagement date

**Structure** (max 60 words):

```
[One sentence acknowledging the timing isn't right]

[One sentence with a concrete re-engagement plan — specific month]

[Signature]
```

### Example

> Marcus,
>
> Understood — timing matters. I'll set a reminder to reach out again in early Q3 with fresh research on the Adtech platform space at that point. Until then, good luck with the first-90-days work.
>
> Marcus
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## Objection replies

For each of the three common objections, the agent uses a scripted structure. **Never invent counter-offers.** Pricing-discount objections in particular route to a human — the agent must never improvise a discount.

### Objection 1 — "Your price is higher than India"

```
[Acknowledge the price differential directly — no denial]

[The Tenacious answer: reliability, overlap hours, retention. Not price.]

[One concrete mechanism — e.g., 18-month average tenure, 3-hour overlap
 guarantee, insurance coverage]

[The ask: a 15-minute conversation to walk through the mechanism, not to
 negotiate price]
```

### Example

> Elena,
>
> Fair — and we're rarely the cheapest. We compete on reliability rather than hourly rate: average engineer tenure is 18 months, 3-hour minimum overlap with your time zone, and a dedicated project manager on every engagement rather than self-service staffing.
>
> The cost comparison worth making is usually not $/hour but delivered-output / $ over the engagement. Happy to walk through what that looks like for your specific stack.
>
> → [Cal link]
>
> Elena
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

### Objection 2 — "We already have a vendor / in-house team"

```
[Acknowledge the existing arrangement is likely working for core scope]

[The gap Tenacious fills — typically specialized capability the incumbent
 doesn't have, or capacity for new initiatives]

[A specific reference to the competitor gap brief finding]

[The ask]
```

### Objection 3 — "We only need a small POC"

```
[Acknowledge that starting small is the right move — never push back]

[Name the $[PROJECT_ACV_MIN] starter-project floor from the pricing sheet]

[Ask the prospect to describe the smallest deliverable that would prove value]

[The ask: discovery call to scope]
```

---

## Hard no — opt-out handling

When a prospect replies with any variant of "not interested," "please remove," "stop emailing," or similar:

1. **No reply.** Do not send an apology or a closing thank-you. The prospect asked to be left alone; respect that directly.
2. **Mark the HubSpot contact record** `outreach_status=opted_out`.
3. **Update the email handler's suppression list** with the prospect's domain.
4. **Log the event to Langfuse** with the reply text for probe-library analysis.

The only exception: if the prospect's reply contains a specific factual correction (e.g., "you have the wrong contact, our CTO is X"), the agent may forward the corrected contact to the enrichment pipeline and close the original thread silently.

---

## Multi-thread safeguard

If the agent is talking to two prospects at the same company (e.g., co-founder and VP Engineering), it must **never** reference content from one thread in the other. Cross-thread leakage is a probe category in Act III and a common failure mode. Each thread carries its own conversation state keyed by prospect email, not by company domain.

---

## When to hand off to a human

The agent hands off — meaning it drafts a context brief for the human delivery lead and explicitly tells the prospect "our delivery lead will follow up within 24 hours" — in these cases:

1. The prospect asks for pricing outside the quotable bands in `seed/pricing_sheet.md`.
2. The prospect asks for specific staffing (e.g., "do you have a Databricks specialist with healthcare experience available starting in July?") that is beyond what `seed/bench_summary.json` can confirm.
3. The prospect asks for a public client reference in a named sector.
4. The prospect references regulatory, contracting, or legal terms (MSA, DPA, specific clauses).
5. The prospect is a C-level executive at a company above 2,000 headcount. These deals go directly to a human regardless of the content of the reply.

The context brief attached to the handoff follows the template in `schemas/discovery_call_context_brief.md`.

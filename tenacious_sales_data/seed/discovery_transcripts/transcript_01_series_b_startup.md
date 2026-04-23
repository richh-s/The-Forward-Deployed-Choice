# Discovery Call Transcript 01 — Series B Startup (Segment 1)

**Synthetic transcript.** Composed from the Tenacious sales team's style. Not a real call.

**Prospect:** Elena Cho, VP Engineering, synthetic Series B infrastructure startup.
**Tenacious lead:** Arun Sharma, Co-founder.
**Length:** ~27 minutes.
**Outcome:** Proposal requested for a 3-engineer Python squad, 6-month initial engagement.

---

**Arun:** Elena, thanks for making time. I saw your hiring-velocity note in the email thread — three Python roles open since February and a handful of data-adjacent ones. Before I say anything about us, what's the story on your side?

**Elena:** We closed Series B in February, $14M. The plan coming out of the round was to hire four senior engineers in Q1 and get them onboarded by April. We've hired one. The recruiting pipeline is thin, and every senior we've found has two other competing offers. We're at the point where we need to either keep grinding on in-house hiring or find a way to bridge.

**Arun:** Your roadmap — what does the delivery pressure look like through Q2 and Q3?

**Elena:** We committed to an infrastructure migration for our two largest customers by end of Q3. The work is Python and Go, mostly data-plane stuff. If we don't have the team in place by mid-Q2, we'll either miss the commitment or our senior engineers burn out trying to cover.

**Arun:** OK. Two things I want to check before I tell you what we'd propose. First — is there any constraint on offshore delivery from a customer-contract perspective? Some infra customers have clauses.

**Elena:** Our contracts have a standard data-handling clause. Offshore is fine as long as access controls are in place. We've run with contractors before.

**Arun:** Good. Second — what's the culture around code review and architectural decisions? Is there a lead architect inside, or is that distributed across the team?

**Elena:** Distributed. We have a tech lead for the data-plane, but architectural calls go through a design-review process — one lead reviews, one other senior reads the doc, decision goes in the wiki.

**Arun:** That's a strong fit for our model. Here's what I'd suggest. A squad of three engineers: one senior, two mid-level ICs, all on the Python side initially. One of our fractional project managers overlays, maybe 0.4 FTE. They join your standups, your code review, your wiki. We don't introduce a parallel review process; our senior integrates into your design-review cadence.

**Elena:** What's the timeline to have them on the product?

**Arun:** Seven to fourteen days for bench engineers. We don't have to hire; we have seven Python engineers on the bench as of Monday. Two I'd flag specifically for the data-plane work — they've both done similar migrations.

**Elena:** Cost?

**Arun:** The base rates from our pricing sheet: junior from $[JUNIOR_MONTHLY_RATE] a month, mid from $[MID_MONTHLY_RATE], senior from $[SENIOR_MONTHLY_RATE]. The fractional PM is separate and pro-rated. For the configuration I described, a month in the low teens. We'd contract on a monthly basis with two-week extension blocks after the first month.

**Elena:** No minimum term?

**Arun:** Minimum one month. If after a month you're not getting what you need, we part ways with no penalty. Most of our clients extend for 6 to 12 months, but the structure is the same.

**Elena:** What's the catch? Usually when an offshore team promises seven days to deploy it means the engineers are new graduates with zero context.

**Arun:** Fair question. Two things. Our engineers are employees, not contractors — salaried, benefits, insurance. Average tenure eighteen months. Second, the two I'd put on your engagement have roughly three years of experience and have done the exact migration type you described. I can share anonymized profiles; names and photos on proposal sign.

**Elena:** The time-zone piece — Pacific time is painful from Ethiopia.

**Arun:** Our engineers work 3-hour overlap with Pacific as a baseline. For the architecture work and design-review participation, that overlap is where we put the concentrated synchronous time. Async for implementation, Slack coverage for the rest. We've done this with two West-coast clients through to production.

**Elena:** OK. What do you need from me?

**Arun:** Three things. One — the name of two of the Python systems we'd be touching, so we can confirm the bench match more specifically. Two — a contact on your side for the security and contracts review; we'd want to get the data-handling walkthrough done before a formal SOW. Three — 48 hours for us to put a one-page proposal together with the specific engineers, start date, and phase-one deliverable.

**Elena:** Forty-eight hours works. What does a phase-one deliverable look like for this engagement?

**Arun:** We typically propose a 4-week phase-one with a specific, measurable output — for your case, probably a demonstration of the data-plane migration working against one of the two customer clusters in staging, with the rollback plan documented. After phase-one you have a natural decision point: continue the squad or part ways.

**Elena:** That's cleaner than what the other two vendors I'm talking to offered.

**Arun:** We'll send the proposal Thursday. One more thing before we wrap — you mentioned your customer contracts. I'd want our legal team to see a sample data-handling clause before we commit. If that's something you can share under NDA we can turn that around fast.

**Elena:** I'll send the clause by EOD.

**Arun:** Perfect. Talk Thursday.

---

## What the call demonstrates

- **Grounded opening** — Arun opens with the specific hiring-velocity fact from the enrichment brief.
- **Qualifying questions before pitching** — the offshore-constraint check and the code-review culture check are both done before any Tenacious capability is described.
- **Pricing transparency without commitment** — Arun quotes the public bands but defers a specific total to the proposal.
- **Bench specificity** — "seven Python engineers on the bench as of Monday" matches `seed/bench_summary.json`. Agents must never exaggerate this.
- **Three concrete next steps** — the close is specific, not "let's stay in touch."
- **Honest objection-handling on time zones** — Arun does not deny the overlap challenge; he describes the specific mechanism for working with it.

## Agent-usable phrases from this call

- "Seven to fourteen days for bench engineers. We don't have to hire."
- "Our engineers are employees, not contractors — salaried, benefits, insurance."
- "3-hour overlap with Pacific as a baseline."
- "Minimum one month. After that, 2-week extension blocks."
- "We typically propose a 4-week phase-one with a specific, measurable output."

## Agent-NOT-usable phrases

- "The best offshore team on the market" — marketing language, bans.
- "Guaranteed 20% margin improvement" — unsubstantiated.
- "You can't find this talent anywhere else" — false.

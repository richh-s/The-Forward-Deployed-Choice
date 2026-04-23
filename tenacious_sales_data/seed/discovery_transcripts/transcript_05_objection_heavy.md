# Discovery Call Transcript 05 — Objection-Heavy (Cross-Segment)

**Synthetic transcript.** Composed from the Tenacious sales team's style. Not a real call.

**Prospect:** Marcus Wahlberg, VP Engineering, synthetic late-stage B2B platform (~600 employees). Skeptical of offshore delivery; previously worked with two offshore vendors at prior company, both bad experiences.
**Tenacious lead:** Arun Sharma, Co-founder.
**Length:** ~31 minutes.
**Outcome:** Agreed to a small $[PROJECT_ACV_MIN] starter engagement to test the delivery model before any larger commitment.

---

**Arun:** Marcus, thanks for taking the time despite the skepticism. You were pretty clear in your email reply that you've seen offshore fail before. I'd rather spend this call testing whether there's any version of this that could work for you than pitching.

**Marcus:** Appreciated. Let me tell you what went wrong before so you can tell me whether you're different. Previous company, we used a large Indian vendor for a two-year platform build. The engineers rotated constantly. Every code review was a context transfer. When we pushed back on quality, the vendor's response was to add another layer of management, which slowed things down further. It was the worst technology procurement decision we made.

**Arun:** Two of those patterns are things we explicitly build against, one is a real risk I want to name. Rotation: our engineers are employees with an 18-month average tenure, and we commit to named-engineer stability for an engagement. If a named engineer leaves, we don't swap without your sign-off. Quality escalation via management layers: we don't have those layers. Your technical lead talks directly to our senior engineer on the engagement. Our project manager coordinates logistics, not technical decisions.

**Marcus:** And the real risk you want to name?

**Arun:** Time-zone overlap. We give three to five hours with US East Coast, less with West Coast. If your culture requires real-time collaboration for most decision-making, we're not the right fit. Some teams can work async for implementation and concentrate synchronous time for design review and unblocking; some teams can't. I'd want to understand which you are before we go further.

**Marcus:** We've been remote-native since 2020. Async works for most implementation. Design review and debugging sessions are synchronous.

**Arun:** Good fit on that dimension.

**Marcus:** Second objection. Your price is probably not cheaper than what I'd pay an Indian vendor, and frankly not cheaper than my own team if I accept slower hiring. What's the cost-side pitch?

**Arun:** We're not the cheapest offshore option. We compete on reliability and retention, not hourly rate. The comparison that usually lands: if you calculate delivered-output per dollar over an 18-month engagement — not hourly rate — our number is better than the Indian vendors for most clients. Because the rotation cost is real. But I won't sell you on a percentage savings without a scoping conversation; any vendor who does that is making up numbers.

**Marcus:** Third objection. I looked at your website. "Public benefit company, 100% African engineers, 33% women." I'm going to push on this. Is this a positioning line or a delivery constraint I need to know about?

**Arun:** Both, honestly. The mission is real — we're deliberately building the next generation of engineering talent out of African universities. That has practical implications: our engineers tend to stay longer because the career path we offer is differentiated, which is good for you. It also means we don't hire outside Africa, which constrains us on specific specializations that are concentrated elsewhere. If you needed, say, a senior kernel engineer with 15 years of Linux kernel experience, we probably don't have them. For most enterprise software work we do, the constraint doesn't bite.

**Marcus:** Honest answer.

**Arun:** Fourth thing you haven't asked about but should. We do not replace in-house architecture. If your team is still forming the architectural thesis for a product area, that's your work. We're most useful when the architecture is clear and the delivery capacity is the bottleneck.

**Marcus:** Noted. OK, given all of that, what would a starting engagement with Tenacious look like if I wanted to test you without betting the company?

**Arun:** The smallest real engagement we do is a fixed-scope project consulting contract. From $[PROJECT_ACV_MIN]. We'd agree on a specific deliverable that can be evaluated objectively in four to six weeks — a specific feature, a specific data pipeline, a specific infrastructure component. If the deliverable lands clean, we can talk about a larger squad engagement. If it doesn't, you've spent $[PROJECT_ACV_MIN] and learned whether we're for real. That's less than one month of one senior engineer's salary in Boston.

**Marcus:** Scope ideas?

**Arun:** I don't know enough about your stack to propose specifics, but from the email context — you mentioned the data-platform migration you're scoping for Q3. A $[PROJECT_ACV_MIN] to $[SMALL_POC_MAX] starter could be "migrate three specific dbt models from your current structure to the proposed target, write the tests, document the pattern for the rest of the team to follow." Small, evaluable, specific. If we deliver, you know our team works; if we don't, you know we don't.

**Marcus:** I'll buy that as a shape. I want to think about it and talk to my data-platform lead. What do you need from me to put a concrete proposal together?

**Arun:** A 30-minute technical walkthrough of the dbt repo, under NDA, with your data-platform lead. From that I can name specific engineers on our side, confirm the scope is achievable in the time window, and send a written proposal within 48 hours.

**Marcus:** Let me book that for next week. Priya will be on it. Send the Cal link.

**Arun:** Will do. One thing I want to flag — if after the technical walkthrough you or Priya decide we're not the right fit, tell us. A "no" saves us both time. I'd rather hear "no, your team doesn't match our stack" than have this slowly fade out over the next six weeks.

**Marcus:** Fair.

**Arun:** Thanks Marcus. Talk next week.

---

## What the call demonstrates

- **Explicitly inviting objections.** Arun opens by acknowledging Marcus's skepticism and framing the call as a test rather than a pitch.
- **Pattern-matching objections to specific mechanisms.** For each objection, Arun maps to a specific Tenacious mechanism (named-engineer stability, no management layers, time-zone overlap).
- **Naming a real Tenacious limitation.** The "we don't hire outside Africa" answer to the positioning question is direct and specific. Prospects frequently probe whether a positioning line is real; the answer must be honest about its operational implications.
- **The $[PROJECT_ACV_MIN] starter-project de-risking path.** The cleanest Tenacious response to a skeptical senior buyer — a small fixed-scope engagement with a specific evaluable deliverable.
- **Explicit invitation to say "no."** Asking the prospect to kill the thread if they decide no is a counterintuitive close that signals confidence and respect for the prospect's time.

## Agent-usable phrases from this call

- "We're not the cheapest offshore option. We compete on reliability and retention, not hourly rate."
- "Any vendor who pitches you a percentage savings without a scoping conversation is making up numbers."
- "We do not replace in-house architecture."
- "The smallest real engagement we do is a fixed-scope project consulting contract. From $[PROJECT_ACV_MIN]."
- "If after the technical walkthrough you decide we're not the right fit, tell us. A 'no' saves us both time."

## Agent-NOT-usable phrases

- "We're not like other offshore vendors" — vague, defensive, low-credibility.
- "Guaranteed 40% cost savings" — the specific thing Arun refuses to commit to in this call.
- "We can handle any stack" — false, and Arun explicitly names the kernel-engineer counter-example.

---

## How to use these transcripts in the agent

Your reply-handling module should treat these transcripts as the source of truth for Tenacious's objection-handling language. When the classifier detects an objection in an inbound reply, the agent should generate a response that pattern-matches to the structure demonstrated here — acknowledge the objection directly, name the specific mechanism, avoid unsubstantiated claims, route to a discovery call for deeper commercial conversation.

**Common mistake to probe for:** agents that summarize multiple transcripts into a generic "tenacious talking points" prompt tend to produce responses that feel vendor-generic. The probe library in Act III should include a tone-drift probe that checks for this specific failure.

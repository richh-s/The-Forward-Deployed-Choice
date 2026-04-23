# Re-engagement Sequence — Stalled Threads

A stalled thread is one where the prospect replied at least once (engaged or curious), then went silent before booking a discovery call. The current Tenacious manual process stalls **30–40% of qualified conversations** in the first two weeks (per `seed/baseline_numbers.md`). Re-engagement is a high-ROI target and one of the strongest memo-level justifications for the full system.

---

## When to trigger re-engagement

The re-engagement sequence fires automatically when:

- Prospect replied at least once and the reply was classified **engaged** or **curious**.
- No booking created on Cal.com within **7 days** of the last agent message.
- No opt-out, hard-no, or soft-defer in the thread.
- Prospect has **not** been re-engaged in the last 45 days.

Each of these is a state check; the agent does not run re-engagement on a timer alone.

---

## The re-engagement principle

Do not "follow up" — **introduce a new piece of information that re-activates the reason the thread was valuable in the first place**. The difference between a pushy sales cadence and a useful re-engagement is whether the new message has independent value.

Three kinds of new information that work for Tenacious prospects:

1. **A new hiring-signal update.** Prospect's job-post count changed, a relevant competitor made a visible move, a new layoff or funding event landed in the sector.
2. **A new research artifact.** A comparison across the prospect's peer group, a summary of a specific sub-niche's AI-maturity trend, a data point from a Tenacious engagement (anonymized) that maps to the prospect's situation.
3. **A relevant conference or announcement.** A specific public event the prospect is likely interested in, framed as a reason to talk before or after rather than generic "wanted to reconnect."

---

## Re-engagement email 1 — "New data point"

**Timing:** 10 days after last agent message in the stalled thread.

**Subject line patterns:**
- `Update on [sector] hiring signal`
- `One thing I noticed since we last spoke`
- `Re: [original subject] — one update`

**Body structure** (max 100 words):

```
[One-line re-opener — references the previous thread specifically, not
 generically. No "just following up."]

[The new data point — grounded in fresh enrichment. Two sentences max.]

[Why this is relevant to the prospect's specific situation.]

[A soft ask — not a calendar link this time, but a question or a
 one-paragraph offer. Escalate to calendar only in Email 2 if engaged.]

[Signature]
```

### Example

> Subject: Update on Adtech hiring signal
>
> Marcus,
>
> Picking up from our thread two weeks back on MLOps staffing.
>
> Noticed that Adludio closed two MLOps-engineer hires this week and posted a third role, and TripleLift quietly opened an AI-platform-engineer req. That moves the sector signal from "peer-gap" to "peer-consolidation" — the window where a managed squad lets you catch up without a 6-month hiring cycle is narrower now.
>
> Happy to share the full sector comparison if useful — reply "yes" and I'll send a one-pager, no calendar ask.
>
> Marcus
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## Re-engagement email 2 — "A specific open question"

**Timing:** 7 days after re-engagement email 1 (if no reply).

**Subject line patterns:**
- `One specific question`
- `Last note on [topic]`

**Purpose:** Ask a single specific question the prospect can answer in one line. Lower the bar for any reply.

**Body structure** (max 50 words):

```
[Single-sentence opener]

[ONE specific question. Not open-ended. The prospect can reply in one
 line or one word.]

[Signature]
```

### Example

> Subject: One specific question
>
> Marcus,
>
> If I may — is the MLOps gap something you're actively scoping, or have you made a deliberate call not to pursue it? Either answer is useful for our research; no follow-up pitch either way.
>
> Marcus
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## Re-engagement email 3 — The 6-month close

**Timing:** 14 days after re-engagement email 2 (if no reply). This is the final touch; after this, the thread is closed and the prospect is parked for 180 days.

**Subject line patterns:**
- `Parking this — Q3 check-in`
- `Closing out, will check back in 6 months`

**Body structure** (max 40 words):

```
[One sentence acknowledging the thread is closed for now]

[Specific re-engagement date — month and year, not "later"]

[Signature]
```

### Example

> Subject: Parking this — Q3 check-in
>
> Marcus,
>
> Closing this thread for now and parking for a Q3 (July) check-in with fresh research. Best of luck with the first 90 days.
>
> Marcus
> Research Partner, Tenacious Intelligence Corporation
> gettenacious.com

---

## SMS re-engagement (warm leads only)

SMS re-engagement is permitted **only** when:

1. The prospect has replied by email at least once (warm lead, not cold).
2. The prospect has explicitly shared a phone number in the thread, OR Tenacious has a verified direct number (public profile, published contact page, LinkedIn "Message me at X").
3. The purpose of the SMS is scheduling coordination only — confirming a time, moving a slot, sending a Cal link.

**SMS is never used for substantive content.** No competitor-gap insights, no pricing, no capability discussion — these are email-only.

### SMS template

```
Hi [Name] — [Agent first name] at Tenacious. Per our email thread:
[specific action, e.g., Tue 10am PT]? Cal confirms at: [short link]. Reply N if the slot no longer works.
```

Under 160 characters, one message, no emojis, no marketing language.

---

## What re-engagement must NEVER do

- **Never apologize for reaching out.** "Sorry to bother you again" is a tone violation.
- **Never reference silence.** "I noticed I haven't heard back" is a tone violation.
- **Never stack multiple new data points in one message.** One new piece of information per re-engagement touch.
- **Never use a deadline-style urgency pattern.** "Before Q2 ends" or "last chance" is banned.
- **Never re-engage a thread with a hard-no, opt-out, or regulatory-conflict flag.** The HubSpot `outreach_status` field gates this.

---

## How re-engagement performance is measured in the memo

Your memo's **speed-to-lead delta** claim (Page 1 of `memo.pdf`) is measured against the current Tenacious manual baseline of 30–40% stalled threads. The calculation:

```
stalled_rate = (prospects who replied engaged/curious but did not book within 14 days) /
               (total prospects who replied engaged/curious)
```

Measured from your trace logs across at least 20 synthetic prospect interactions. Claiming a lower stalled rate than the manual baseline requires:

1. Trace evidence (trace IDs cited in `evidence_graph.json`).
2. An honest denominator — do not exclude threads that went to SMS or voice; count all qualified-reply threads.
3. A note on sample size and confidence interval.

Under-claiming with a note about limited sample size is acceptable. Over-claiming a 90% reduction without trace evidence is a disqualifying violation.

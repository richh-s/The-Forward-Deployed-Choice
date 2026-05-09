# Day 1 — Building a Signal-Grounded Outreach Engine from Scratch

**10Academy Forward-Deployed AI Challenge | Week 10 | Tenacious Consulting Scenario**

📖 [Read on Medium](https://medium.com/@rahelsamson953/day-1-building-a-signal-grounded-outreach-engine-from-scratch-0bee76760bbe)

---

Most B2B outreach fails before it starts. A sales rep sends the same templated email to 200 companies, gets a 2% reply rate, and calls it a win. The problem is not the email. It is that nothing in the email is grounded in what the prospect is actually going through right now.

This week I took on a challenge: build an AI system that automates first-touch outreach for Tenacious Consulting, a firm that places senior engineering talent. The constraint that made this interesting — no generic emails. Every message had to be grounded in real, verifiable signals about the prospect. No hallucinated facts. No invented claims. If the system was not sure, it had to say so.

Day 1 was about building the foundation: a signal enrichment pipeline and an ICP classifier that decides who the prospect actually is before a single word of outreach is written.

---

## The Problem with Generic Outreach

Tenacious Consulting sells to engineering leaders — CTOs, VP Engs, Heads of Platform. These are people who receive 20 cold emails a day. They delete anything that sounds templated in under three seconds.

The only emails that get replies are ones that demonstrate the sender actually knows something about the recipient's situation. Not their job title. Their *situation* — what is happening at their company right now that makes them likely to need engineering talent.

That is what signal grounding solves.

---

## Six Signals, One Classification

The enrichment pipeline I built on Day 1 pulls six signals for every prospect before any email is written:

**Signal 1 — Funding Event (Crunchbase)**
Did they close a Series A or B in the last 180 days? A fresh funding round means budget has landed and engineering hiring is imminent. This is the most reliable buying signal for Tenacious.

**Signal 2 — Job-Post Velocity (Wellfound + Playwright)**
How many engineering roles are open right now, and how fast is that number growing? A spike in open roles means hiring is already underway and they may be struggling to fill seats.

**Signal 3 — Layoff Event (layoffs.fyi CSV)**
Did they cut headcount in the last 120 days? A company in cost-restructuring mode needs a completely different pitch than one in growth mode. Getting this wrong is not just ineffective — it is tone-deaf.

**Signal 4 — Leadership Change (Crunchbase People API)**
Is there a new CTO or VP Engineering in the last 90 days? New engineering leaders almost always audit the existing team and vendor relationships. They are highly receptive to external partners.

**Signal 5 — AI Maturity Score (Composite 0–3)**
Do they have public AI signal? This is a composite score built from six indicators: AI-adjacent open roles, named ML leadership, modern data stack, GitHub org activity, executive AI commentary, and strategic communications. Scored 0 to 3.

**Signal 6 — ICP Segment (Derived)**
This one is never fetched from an external source. It is always computed from Signals 1–5. This distinction matters: the segment classification is only as good as the upstream signals, and the system knows it.

---

## The ICP Classifier: Four Segments, Strict Priority Order

Every prospect lands in one of four segments — or the system abstains:

- **Segment 1 — Recently Funded:** Series A/B ≤ 180 days, no layoff, ≥ 5 open engineering roles. Pitch: scale your team while capital is fresh.
- **Segment 2 — Cost Restructuring:** Layoff ≤ 120 days, cost pressure dominates. Pitch: do more with fewer headcount through senior fractional talent.
- **Segment 3 — Leadership Transition:** New CTO or VP Eng ≤ 90 days. Pitch: give the new leader an early win with proven external partners.
- **Segment 4 — AI Capability Gap:** AI maturity score ≥ 2, missing ML talent. Pitch: close the gap before competitors do.

The priority order matters: a company that raised Series A *and* had layoffs gets the Cost Restructuring pitch — Segment 2, not Segment 1. Layoff overrides funding. Leadership change overrides AI maturity. This hierarchy prevents the most common classification mistake, which is pitching growth to a company in survival mode.

When a prospect matches multiple segments, a **conflict flag** is raised and the system routes to human review rather than guessing.

When signals are too weak to classify with confidence, the system **abstains** — returning `segment_number: 0` — and sends a short generic exploratory email with no product claims.

---

## The τ²-Bench Baseline

Alongside the pipeline, I ran the τ²-Bench retail domain evaluation to establish a performance baseline. The results: **72.67% pass@1** across 30 tasks × 5 trials = 150 simulations. The published reference for this benchmark sits at 42%, so the baseline already beats it by +30 percentage points.

This number becomes the floor everything else has to improve on. More importantly, it reveals something I will come back to on Day 3: benchmark scores and production safety are two very different things.

---

## The One Rule That Matters Most

The most important design decision from Day 1 is also the simplest: **Signal 6 is always derived, never fetched.**

If the enrichment pipeline cannot produce enough signal to classify a prospect, the system does not guess. It abstains. An email never goes out on a classification the system is not confident about.

This sounds obvious. Almost every production AI system I have seen violates it.

---

## What Comes Next

Day 1 gave us signals and a classifier. Day 2 is about turning those signals into real actions — a live email delivered, a HubSpot contact created, an SMS sent, and a voice call queued.

The pipeline runs. The classification works. Tomorrow we find out if the whole thing holds together end to end.

---

*Built as part of the 10Academy Forward-Deployed AI Challenge. All code in this project is for the Tenacious Consulting scenario only — zero CFPB or regulatory fields anywhere in the stack.*

---

**Read this post on Medium:** [Day 1 — Building a Signal-Grounded Outreach Engine from Scratch](https://medium.com/@rahelsamson953/day-1-building-a-signal-grounded-outreach-engine-from-scratch-0bee76760bbe)

**Continue to Day 2:** [From Enrichment to a Live End-to-End Pipeline](https://medium.com/@rahelsamson953/day-2-from-enrichment-to-a-live-end-to-end-pipeline-d2c52a11d4de)

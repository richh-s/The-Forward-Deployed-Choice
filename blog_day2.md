# Day 2 — From Enrichment to a Live End-to-End Pipeline

**10Academy Forward-Deployed AI Challenge | Week 10 | Tenacious Consulting Scenario**

---

Day 1 gave us a signal enrichment pipeline and an ICP classifier that could tell us who a prospect is and which pitch they should receive. Day 2 was about making something actually happen in the world as a result.

By the end of today, a real email landed in a real inbox. A HubSpot contact was created. An SMS was delivered. A voice call was queued. Every step was logged, costed, and traceable. The happy path runs.

---

## The Full Pipeline, Step by Step

The architecture follows a deliberate channel hierarchy: email first, SMS only after a warm reply, voice only for final escalation. Here is what that looks like in practice.

**Step 1 — Enrichment and Classification**
The prospect's company data runs through the six-signal pipeline from Day 1. For our test prospect — NovaPay Technologies — the classifier returned: Segment 3 (Leadership Transition, new CTO 60 days ago) with a conflict flag because Segments 1 and 4 also matched. Conflict flag means the system routes to inquiry mode rather than a bold assertion pitch.

**Step 2 — Email Composition**
The email agent (gpt-4o-mini via OpenRouter) receives the enrichment brief, the competitor gap analysis, and the bench summary. It composes a personalised outreach email in JSON format — subject line, body, and tagged metadata including the segment, the phrasing mode used, and the average signal confidence.

The actual email that landed in the inbox had the subject line: *"Aligning Engineering Strategies Post-Transition."* The body referenced NovaPay's leadership change, their 12 open engineering roles, and their AI maturity gap — every claim sourced from the enrichment pipeline, none invented.

**Step 3 — Delivery via Resend**
Resend delivered the email and returned a message ID. Cost: $0.007. The full compose-and-send latency (p50 across 50 runs): 2.87 seconds.

**Step 4 — HubSpot Contact Creation**
The pipeline creates a HubSpot contact with standard fields — name, email, company, job title — and updates the lifecycle stage. Contact ID `477559194332` was returned. When HubSpot returns a 409 (contact already exists), the system searches by email and returns the existing ID rather than failing.

**Step 5 — Webhook Reply Handling**
The reply classifier receives the inbound email via a `/webhooks/resend` endpoint. It checks for warm keywords (interested, let's talk, schedule, curious, happy to chat) versus opt-out signals (STOP, UNSUBSCRIBE, CANCEL). A warm reply triggers the SMS handoff.

**Step 6 — SMS via Africa's Talking**
The SMS handler sends a follow-up message to the prospect's phone. Real delivery confirmed: ATXid `57053d4d`, cost $0.02, status: Success. TCPA opt-out keywords are intercepted before any LLM sees the message — this is a hard gate, not a suggestion.

**Step 7 — Voice Escalation via Twilio**
For prospects who have replied via SMS but not booked, the voice agent queues an outbound call. Twilio call SID `CA4eb61f333e8635f6213b5b3c980e3ee3` was returned. Voice is the final escalation tier — it requires the highest cognitive commitment from the prospect, so it is reserved for late-stage warm leads only.

---

## The Confidence Kill-Switch

The most important feature of Day 2 is not a channel. It is a single threshold check that runs before any email is composed.

Every prospect's enrichment signals each carry a confidence field — `high`, `medium`, or `low`. The system computes a weighted average:

```
high   → 1.0
medium → 0.7
low    → 0.4

avg_confidence = mean(confidence scores across all six signals)
```

If `avg_confidence >= 0.70`, the agent operates in **Assertion Mode**:
> "You raised $12M in Series A 45 days ago."

If `avg_confidence < 0.70`, the agent switches to **Inquiry Mode**:
> "I understand you may have recently completed a funding round — is that accurate?"

This is not just a safety feature. It is the mechanism that makes the system trustworthy enough to run without a human reviewing every email. When the pipeline is not sure, it asks instead of asserts.

---

## The Webhook Server: One Entry Point for Everything

All inbound events route through a single FastAPI server deployed to Render:

| Endpoint | Handles |
|---|---|
| `/webhooks/resend` | Email delivery events and inbound replies |
| `/webhooks/sms` | Inbound SMS from Africa's Talking |
| `/webhooks/calcom` | Cal.com booking confirmations |
| `/webhooks/hubspot` | CRM lifecycle updates |
| `/webhooks/voice` | Twilio voice call routing |
| `/internal/register-prospect` | Registers email→phone mapping for reply routing |

The `/internal/register-prospect` endpoint solves a non-obvious problem: when an email reply comes in, the system needs to know which phone number to SMS. This endpoint registers the mapping at send time so the reply handler can look it up.

---

## The Numbers

| Metric | Value |
|---|---|
| Cost per conversation | $0.0059 |
| p50 email compose latency | 2.87s |
| p95 email compose latency | 4.19s |
| HubSpot contact created | ID 477559194332 |
| SMS delivered | ATXid 57053d4d, $0.02 |
| Budget target (Tenacious) | $5.00/lead |
| Kill-switch threshold | $8.00/lead |

We are at 0.1% of the per-lead budget cap. The system runs well within the economic envelope.

---

## What I Did Not Claim

The Cal.com booking in the happy path is triggered by the SMS handoff, not by the initial email send. I removed an earlier version that pre-booked a slot at send time — that was wrong. The booking should only happen when the prospect explicitly asks for it. Getting this sequence right matters: a pre-booked meeting nobody agreed to is not a feature, it is spam.

The HubSpot contact fields are limited to standard properties — name, email, company, job title, lifecycle stage. There are no custom fields, no CFPB fields, no regulatory data of any kind. The scenario is Tenacious Consulting only.

---

## What Comes Next

The happy path works. Tomorrow, Day 3, I deliberately break it — 32 adversarial probes across 10 failure categories designed to find every way the system can embarrass Tenacious Consulting in front of a prospect. The results are not pretty. But they are honest.

---

*Built as part of the 10Academy Forward-Deployed AI Challenge. All code in this project is for the Tenacious Consulting scenario only.*

---

**Read this post on Medium:** [Day 2 — From Enrichment to a Live End-to-End Pipeline](https://medium.com/@rahelsamson953/day-2-from-enrichment-to-a-live-end-to-end-pipeline-d2c52a11d4de)

**Back to Day 1:** [Building a Signal-Grounded Outreach Engine from Scratch](https://medium.com/@rahelsamson953/day-1-building-a-signal-grounded-outreach-engine-from-scratch-0bee76760bbe)

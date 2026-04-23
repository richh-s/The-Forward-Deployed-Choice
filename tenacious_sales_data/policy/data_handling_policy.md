# Data Handling Policy — TRP1 Week 10

This policy governs what you may do with what data during the Week 10 challenge.
Read it carefully. Signing `acknowledgement.md` confirms you have read and agreed
to abide by every clause below. Violations are grounds for removal from the
program.

## Scope

This policy applies to:

- Every piece of data in `seed/` and `schemas/` in this repo.
- Every record your enrichment pipeline retrieves from public sources.
- Every prospect your system interacts with during the challenge week.
- Every trace your system writes to Langfuse, HubSpot, or any other system.

## Rule 1 — No real Tenacious customer data leaves Tenacious

You do not receive CRM exports, email threads with real prospects, real phone
numbers, or real names of live deals. The seed materials in this repo are
abstracted, anonymized, or synthetic. If you believe you have received real
customer data by mistake, report it to tutors immediately and delete it from any personal infrastructure.

## Rule 2 — Every prospect the system contacts during the challenge week is synthetic

Every prospect your system interacts with during the challenge week is a
synthetic profile derived from public Crunchbase, LinkedIn job-post, and
layoffs.fyi data. Synthetic contact details (fictitious names, program-operated
email addresses, program-operated phone numbers) are used to ensure no real
person receives an outreach from your system.

The program-operated sink routes all outbound to a staff-controlled destination.
The kill switch (see `infra/killswitch.md`) enforces this technically.

**You may not use real company contact addresses** — not even ones you find on
a public website — during the challenge week. If your system has a
`contact@examplecompany.com` in its queue, that address resolves to the sink,
not to Example Company.

## Rule 3 — Seed materials are licensed for the challenge week only

The seed materials (ICP, style guide, sales deck, case studies, pricing,
bench summary, baseline numbers) are shared under the limited license in
`LICENSE.md`. You may:

- Read, reference, and adapt them inside your program repo during the week.
- Quote them in your agent prompts and documentation.
- Retain your program repo after the week, subject to the redactions listed
  in `LICENSE.md`.

You may not:

- Redistribute the seed materials outside your program repo.
- Publish them on a personal blog, portfolio, or job application.
- Quote client names or case-study references beyond what is in the
  anonymized materials.

## Rule 4 — Public-source scraping rules

For every public source your enrichment pipeline uses:

- **Public pages only.** Do not log in to any service. Do not use stored
  cookies or session tokens to access gated content. 
- **Do not bypass captchas.** If a page shows a captcha, stop the scrape and
  log it as `status: rate_limited` in your `data_sources_checked` field.
- **Respect robots.txt.** Check the target domain's robots.txt before
  scraping. If the target forbids scraping a specific path, do not scrape it.
- **Rate limit.** At least 2 seconds between requests to the same domain.
  No more than 3 concurrent tabs on the same domain.
- **User agent.** Identify as
  `TRP1-Week10-Research (trainee@trp1.example)` — do not impersonate a
  browser or a named crawler.
- **Cap on live crawl.** No more than 200 companies live-crawled during the
  challenge week. Most of your enrichment comes from the frozen April 2026
  snapshot in `data/job_posts_snapshot_2026-04-01.json`.

## Rule 5 — The kill switch is not optional

The `TENACIOUS_OUTBOUND_ENABLED` flag (see `infra/killswitch.md`) must default
to unset in your `.env`. Every outbound call must pass through the gate
function. Bypassing the gate in code — even for a single test message — is a
policy violation, regardless of whether the bypass accidentally reaches a real
prospect or not. The policy is about the code pattern, not the outcome.

Your README must document the kill switch explicitly, and your code must
include a smoke test (provided in `infra/smoke_test.sh`) that confirms the
gate is in place before the agent starts processing outbound.

## Rule 6 — Tenacious-branded output is marked draft

Any outputs of your system that include Tenacious-branded content — cold
emails, call scripts, proposal snippets, pricing — must be marked `draft` in
metadata. The Tenacious executive team reserves the right to redact any such
content from your final memo.

The "mark as draft" requirement means:

- Emails produced by the composer include `X-Tenacious-Status: draft` in the
  message headers.
- Any HubSpot record created includes `tenacious_status=draft` in the
  properties.
- Any content in your final memo that reproduces Tenacious-branded language
  is flagged in the evidence graph.

## Rule 7 — Data minimization in traces

Langfuse and HubSpot traces should log only what is necessary for:

- Evaluating the agent's performance.
- Producing the evidence graph for the memo.
- Debugging failures.

Do not log:

- Full prospect PII beyond what is necessary for the thread (first name and
  email are fine; home address, personal phone, social-security-equivalent
  IDs are not).
- Any payment or banking information.
- Any content that could plausibly be regulated under HIPAA, GDPR health
  categories, or similar.

If you are uncertain whether a specific field should be logged, default to
not logging it.

## Rule 8 — Non-disclosure of Tenacious internal data

Do not add any Tenacious internal data to any public repository or platform.

## Rule 9 — Incident reporting

If you discover that your system has:

- Sent outbound to a real (non-sink) recipient,
- Logged real customer PII to a trace,
- Retrieved data in a way that may violate a public source's terms,
- Or done anything else that you believe may violate this policy,

**stop the agent immediately** and post in Slack with a brief description 
and the timestamp. Program staff will help you
assess and remediate. Reporting an accidental violation honestly is treated
much more favorably than hiding it; undisclosed violations discovered after
the fact are grounds for removal from the program regardless of intent.

## Rule 10 — Questions

When in doubt, ask. Policy questions, contact tutors. This policy is deliberately conservative; if a specific thing you want to do
doesn't fit cleanly into the rules above, ask before you do it.

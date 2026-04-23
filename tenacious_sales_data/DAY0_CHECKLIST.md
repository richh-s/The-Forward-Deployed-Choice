# Day 0 — Pre-flight Checklist

Complete every item below before the Day 1 morning readiness review. Expected time: roughly four hours. Items are ordered by likely dependency, not importance — every item is required.

## Accounts and API keys

- [ ] **Resend** (or MailerSend) account provisioned on the free tier. Test email sent to your own address and received. Webhook URL registered for inbound reply handling. Record API key in `.env`.
- [ ] **Africa's Talking sandbox** account created. Virtual short code registered. One test SMS routed to your local webhook handler. Record API key and short code in `.env`.
- [ ] **HubSpot Developer Sandbox** app created. MCP server installed per [HubSpot MCP docs](https://developers.hubspot.com/). One test contact created via API. Record app ID and private app token in `.env`.
- [ ] **Langfuse** cloud free-tier project created. One test trace visible in the dashboard. Record public and secret keys in `.env`.
- [ ] **OpenRouter** account with at least $[DEV_LLM_COST_MAX] credit for dev-tier model usage (Qwen3-Next-80B-A3B or DeepSeek V3.2).
- [ ] **Anthropic or OpenAI** account for eval-tier scoring (Claude Sonnet 4.6 or GPT-5 class) with at least $[EVAL_LLM_COST_MAX] credit. This is used for the sealed held-out slice only.

## Local infrastructure

- [ ] **Cal.com** running locally via `docker compose up` from `infra/docker-compose.yml`. One test booking flows end-to-end (create event type → book slot → confirmation email received).
- [ ] **Playwright** installed and headless browser working. The 10-line sample in `enrichment/job_post_scraper.py` fetches one public job listing from BuiltIn or Wellfound and prints JSON.
- [ ] **Python environment** — Python 3.11+, venv or uv, `pip install -r agent/requirements.txt` succeeds.

## Benchmark

- [ ] **τ²-Bench** cloned from `github.com/sierra-research/tau2-bench`. Retail domain runs against your pinned dev-tier model on three tasks and produces a score without crashing.
- [ ] **Sealed held-out partition** (20 tasks) received from program staff via encrypted channel and stored outside the repo. Your dev-slice runs use only the 30-task dev partition that ships with the benchmark.

## Seed materials review

- [ ] Cloned this seed repo. `seed/icp_definition.md`, `seed/style_guide.md`, `seed/sales_deck.pptx`, `seed/email_sequences/`, `seed/discovery_transcripts/`, `seed/pricing_sheet.md`, `seed/bench_summary.json`, `seed/baseline_numbers.md` all present.
- [ ] `seed/style_guide.md` read carefully. You can name the five tone markers from memory before writing any outreach code.
- [ ] `seed/icp_definition.md` read. You can name the four segments, the qualifying signal for each, and the disqualifying signals from memory.
- [ ] At least two of the five sample discovery transcripts read to understand Tenacious's objection-handling patterns and pricing language.

## Policy

- [ ] `policy/data_handling_policy.md` read.
- [ ] `policy/acknowledgement.md` signed (digital signature via program form — link in Slack) and confirmation received from program staff.
- [ ] Kill-switch flag `TENACIOUS_OUTBOUND_ENABLED` in `.env` **is unset**. Confirmed by running `grep TENACIOUS_OUTBOUND_ENABLED .env` and seeing either no output or the value commented out. Default must be unset — every outbound request routes to the staff sink unless explicitly enabled.

## Proof of readiness — one-command smoke test

Once every item above is checked, run:

```bash
bash infra/smoke_test.sh
```

Expected output: five green checks, one per stack component (email, SMS, HubSpot, Cal.com, Langfuse). If any check fails, the Day 1 readiness review will not pass and you will work the morning session on unblocking rather than Act I.

## Common Day 0 mistakes

- **Burning the eval-tier budget on dev probing.** Do not run Claude Sonnet 4.6 or GPT-5 against your dev slice. That budget is reserved for the sealed held-out slice in Act IV. Use the dev-tier model (Qwen or DeepSeek via OpenRouter) for everything until Day 5.
- **Testing Cal.com booking against a real calendar.** Use the program-provided mock calendar fixtures in `infra/cal_fixtures/` (downloaded after acknowledgement is signed). Booking against a real calendar during the challenge week is a policy violation.
- **Skipping the τ²-Bench reproduction check.** Your Day 1 baseline must reproduce a published τ²-Bench retail number within a 95% CI. Skipping this step now means Act I takes two days instead of one.
- **Forgetting to register the inbound email webhook.** Resend and MailerSend both require a verified webhook URL for reply handling. Use ngrok or Cloudflare Tunnel for local dev — document the URL in `.env`.

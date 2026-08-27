# Conversion Engine — Product & Operations Guide

Multi-tenant AI outbound conversion platform: signal-grounded email outreach
composed by Claude, gated by an LLM judge and human approval, with a
conversational reply agent, SMS/WhatsApp conversations, Cal.com booking, HubSpot sync, and a
compliance layer (durable suppression, kill-switch, sink mode) built in.

This document is the handover reference for operating it as a product.

---

## 1. Architecture

```
                 ┌────────────────────────────────────────────────┐
                 │  FastAPI app (server.py → engine/app.py)       │
                 │                                                │
  Browser ──────▶│  Dashboard (session auth, admin/operator)      │
                 │  /login /campaigns /approvals /analytics ...   │
                 │                                                │
  Providers ────▶│  Webhooks (signature-verified, fail-closed,    │
  Resend         │  idempotent via WebhookEvent ledger)           │
  Cal.com        │      │ enqueue only — no inline side effects   │
  Africa's Talk. │      ▼                                         │
  Twilio         │  Job queue (Postgres, SKIP LOCKED, retries     │
                 │  w/ exponential backoff, dead-letter)          │
                 │      │                                         │
                 │      ▼                                         │
                 │  Workers: compose → judge → (auto)approve →    │
                 │  send │ reply agent │ HubSpot sync │ booking   │
                 │                                                │
                 │  Scheduler (60s): campaign ticks, follow-ups,  │
                 │  kill-switch evaluation                        │
                 └────────────────────────────────────────────────┘
                                    │
                              Postgres (Alembic migrations)
```

Every business row carries a `workspace_id`; every query filters on it. One
deployment serves many client workspaces, each with its own playbook,
credentials (encrypted at rest), suppression list, campaigns, and users.

### The outbound pipeline

1. **Campaign tick** (scheduler): moves up to `daily_cap` new/enriched
   prospects per day, inside the campaign's send window, into composition.
   With an **enrichment source** configured (Settings → credentials →
   `enrichment`: an https endpoint receiving `POST {email, name, company,
   title, phone}` and returning `{"signals": {...}}`), `new` prospects are
   enriched first and only composed once their signals arrive; if the
   source stays down through the retry budget, the prospect proceeds
   unenriched (inquiry mode) rather than stalling. Operators can also
   trigger **Compose draft now** from any prospect page to preview the
   composer + judge without waiting for the scheduler.
2. **compose_draft** job: Claude composes from the workspace playbook + the
   prospect's enrichment signals. The validated confidence-gating mechanism is
   preserved: average signal confidence ≥ 0.70 → assertion mode, otherwise
   inquiry mode. Output is schema-constrained JSON (no parse failures).
3. **Judge gate**: a second model call scores the draft on signal grounding,
   mode compliance, tone, structure, and hallucination risk. A fabrication
   caps the score at 0.4 (fails everything). Score < 0.6 → one automatic
   regeneration with the judge's feedback.
4. **Approval**: `require_approval=true` (default) puts the draft in the
   dashboard queue for human edit/approve/reject; otherwise drafts scoring
   ≥ `auto_approve_score` go straight to send. Bulk approve is available
   (threshold clamped to [0, 1]; unjudged reply drafts are never bulk-
   approved). Any pending draft can be **test-sent to the reviewer's own
   address** (`[TEST]`-prefixed, no prospect contacted) to verify
   credentials and rendering end to end. The approval card is
   **evidence-linked**: per-dimension judge scores plus the composer's
   claim→signal grounding notes alongside the raw signal brief — every
   sentence is auditable before it sends. Approving records the **edit
   distance** between the AI draft and what the human actually sent.
5. **send_draft** job: policy checks (workspace pause → suppression list →
   touch ceiling → daily cap **shaped by domain warm-up** — a new sending
   domain ramps from `WARMUP_START_PER_DAY` by `WARMUP_DAILY_GROWTH`×/day
   toward the full cap, so early volume can't burn the domain), then Resend
   send with a per-prospect unsubscribe link and RFC 8058 one-click
   unsubscribe headers. In sink mode the recipient is replaced by
   `SINK_EMAIL` with the intended recipient in a header.
6. **Follow-ups**: the campaign sequence (`[{day_offset, angle}, ...]`)
   schedules the next touch; any inbound reply cancels the sequence.
   Follow-ups honor the campaign send window (a due follow-up waits for the
   next in-window pass), and a prospect with no recorded sends never gets a
   follow-up composed against the wrong sequence step.

### The inbound pipeline

- **Email replies** arrive via the Resend inbound webhook. **SMS** arrives via
  Africa's Talking. **WhatsApp** arrives via Twilio
  (`/webhooks/{slug}/whatsapp`, signature-verified) — WhatsApp is a
  *conversation* channel: the reply agent answers inside Meta's 24-hour
  service window on the channel the prospect wrote on; cold outbound over
  WhatsApp (which requires pre-approved templates) is deliberately not
  offered. STOP/START/HELP are handled synchronously on every channel
  (compliance); everything else is recorded on the prospect's timeline and
  queued.
- **inbound_message** job runs the reply agent (Claude, full conversation
  history, playbook-only facts): classifies intent (warm / question /
  objection / neutral / cold), drafts the channel-appropriate reply with the
  personalized Cal.com booking link, and flags escalations (pricing beyond
  public bands, legal, anger, out-of-playbook questions) to the dashboard.
  The reply itself goes through the **same Draft gate as outreach**: by
  default (`require_reply_approval`, per workspace in Settings) it lands in
  the approval queue for human review; workspaces that opt into auto-send
  still have **escalated replies always held** — model output produced from
  attacker-controllable inbound text never reaches a prospect unreviewed
  unless an admin explicitly chose that. Sending a reply never advances the
  touch count or follow-up sequence — and the per-prospect touch ceiling
  never blocks a reply: it bounds outreach volume, not answers to someone
  who wrote in.
- **Cold intent** → both channels suppressed, prospect → `opted_out`, no reply.
- **Cal.com webhook** (BOOKING_CREATED/CANCELLED/RESCHEDULED) records the
  booking, advances the prospect to `booked`, and queues the HubSpot update.
  Confirmed bookings starting within 24h get an **SMS reminder** (no-show
  reduction) — transactional, one per booking, suppression always honored.
- **HubSpot** carries full lead provenance (Crunchbase record id, ICP
  segment, AI-maturity score, funding amount, signal confidence, enrichment
  timestamp — custom properties created by
  `scripts/setup_hubspot_properties.py`, with graceful fallback to standard
  fields on portals without them), and **every conversation event** on any
  channel is logged as a Note on the contact timeline.

### The learning loop

The pipeline reads its own outcomes back (Analytics → Learning):

- **Angle performance**: replies and bookings attributed to the last touch
  that preceded them, per campaign angle — promote what works.
- **Judge calibration**: human approval rate and average edit per judge-score
  band, with a recommended `auto_approve_score` once a band shows ≥95%
  human approval on ≥10 reviewed drafts.
- **Edit telemetry**: every approval records how much the human changed the
  draft; trending toward zero means the composer has earned trust.
- **Judge fine-tuning export** (Settings): reviewed drafts as JSONL —
  signals + draft + API-judge verdict + the human decision as label — ready
  to train a workspace-specific judge for the `local:` judge seam.

### Operator notifications (Slack)

Configure a Slack incoming webhook (Settings → credentials → slack) and the
engine posts where operators live: drafts and replies awaiting review,
escalations, kill-switch pauses, and the weekly digest. Best-effort — a
Slack outage never fails a job.

### Weekly digest

Every Monday each workspace's admins receive an ROI digest (sends, replies,
qualified leads, meetings, bounce/opt-out rates, LLM spend, cost per
meeting) by email and Slack. `WEEKLY_DIGEST_ENABLED=false` turns it off.

## 1a. LLM backends (Claude + self-hosted local models)

Every model call goes through `engine/services/llm.py`, which supports two
backends selected per role by the model string:

- **Anthropic** (default): `COMPOSE_MODEL` / `REPLY_MODEL` / `JUDGE_MODEL` set
  to a `claude-*` id. Per-workspace API key (Settings → credentials) falls
  back to the platform `ANTHROPIC_API_KEY`.
- **Local / self-hosted**: any model string prefixed `local:` is served from
  `LOCAL_LLM_BASE_URL` (an OpenAI-compatible `/v1` endpoint — Ollama, LM
  Studio, vLLM, llama.cpp). Local calls cost **$0** and never leave the
  private network.

**Recommended split** (validated on this deployment): customer-facing
compose/reply on Claude Opus 5; the high-volume **judge on a local model** over
the tailnet. The judge does structured scoring, not prose, so a local model is
a good fit.

```bash
# Ollama/vLLM served over Tailscale from the GPU box (edgexpert, NVIDIA GB10):
LOCAL_LLM_BASE_URL=http://100.81.184.6:11434/v1   # or its MagicDNS name
JUDGE_MODEL=local:gemma-4-26b
```

Reasoning-model handling built into the local backend: a generous output-token
floor (`LOCAL_LLM_MIN_MAX_TOKENS`, default 4096) so thinking doesn't truncate
the answer; a longer timeout (`LOCAL_LLM_TIMEOUT_SECONDS`, default 180s);
tolerant JSON extraction (code fences, leading prose, reasoning-channel markers
stripped); a `response_format` json_schema attempt that falls back to
prompt-only JSON if the server rejects it, plus one corrective retry; and score
clamping to [0,1] since local servers don't strictly enforce schema min/max.
Measured: `gemma-4-26b` scores a draft in ~20–25s at $0, correctly flagging
fabricated claims (score capped at 0.4 → auto-regenerate).

Operational notes: single-model Ollama can return a transient 500 while
swapping models (the backend retries 5xx with backoff); keep the judge model
resident, or use vLLM (`http://<host>:8000/v1`, model `Qwen/Qwen3.6-35B-A3B`
on this deployment) which holds one model loaded. Because the models are on the
tailnet, `LOCAL_LLM_BASE_URL` only resolves when the app host is also on the
tailnet — set it empty in a non-tailnet deploy to keep every role on Claude.

## 2. Security & compliance model

| Concern | Implementation |
|---|---|
| Auth | DB-backed sessions (only the token hash is stored; sliding renewal, server-side expiry, **absolute lifetime cap** — no cookie is immortal however active), bcrypt passwords hashed off the event loop, timing-equalized login (no user-enumeration oracle), login rate limiting (per IP and per IP+account), admin/operator roles, password change with revoke-all-sessions |
| Account recovery | Admin-created users get a temporary password and **must set their own at first login** (enforced on every route until they do). Admins can issue a one-time temporary password for a locked-out teammate (shown once in the response body, never in a URL; all their sessions revoked). Sole-admin lockout: `python scripts/reset_admin_password.py --email …` against the database |
| Bootstrap | One-shot `/setup`, additionally gated by a deploy-time `SETUP_TOKEN` in production and serialized with an advisory lock (no first-visitor-becomes-admin, no double-bootstrap race) |
| CSRF | Every state-changing dashboard route requires a CSRF token (session-derived HMAC; double-submit cookie for the pre-login forms), enforced router-wide. Webhooks are signature-verified and cookie-free; the RFC 8058 unsubscribe POST is deliberately exempt |
| Headers | `X-Frame-Options: DENY`, CSP with `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS in production |
| Tenancy | `workspace_id` on every row; ownership re-checked on every mutating route; webhook-supplied ids (Cal.com metadata) validated against the workspace; job payload workspace/prospect pairs cross-checked |
| Webhooks | Fail closed. Svix (Resend, with ±5 min timestamp tolerance against replay), HMAC-SHA256 (Cal.com), Twilio request signing, secret URL token (Africa's Talking — it does not sign; missing event ids fall back to a content fingerprint for dedup). No secret configured → requests rejected |
| Idempotency | `WebhookEvent` unique ledger per (provider, event id); job `idempotency_key` unique index; Resend sends carry an `Idempotency-Key` header so even a retry after a post-send DB failure cannot deliver twice. Duplicate inserts are absorbed in SAVEPOINTs — they never roll back the surrounding transaction |
| Suppression | Durable DB table per (workspace, channel, address); written on STOP, unsubscribe, bounce, complaint, cold intent, manual action; checked before **every** send *and re-checked at the last instant before the provider call*. STOP confirmations bypass policy checks as required by carrier rules |
| Unsubscribe | Every email carries `List-Unsubscribe` + one-click POST + a visible link to `/u/{token}`. The GET renders a confirmation page only (mail scanners prefetch links); the POST performs the write. Rate-limited |
| Sink mode | `LIVE_MODE=false` (default) reroutes all outbound to `SINK_EMAIL`/`SINK_PHONE`. Missing sink → send refused, never silently delivered |
| Kill-switch | Rolling 7-day opt-out rate, bounce rate, cost per qualified lead (20-send floor), **plus an absolute LLM spend ceiling** that trips even at zero conversions — and even at zero *sends*: compose/judge spend is counted on the Draft the moment it is incurred, so a compose→reject loop cannot burn budget invisibly. Breach → workspace outbound paused + audit log; admin reviews and resumes in Settings. Resuming sets a watermark: only activity *after* the resume counts toward the next evaluation, so the same already-reviewed window cannot instantly re-trip the switch. Thresholds are editable per workspace in Settings → Outbound control |
| Volume caps | Per-workspace daily email/SMS/WhatsApp caps (atomic SQL increments — no race overshoot), campaign `daily_cap` enforced per calendar day, per-prospect touch ceiling (default 4), email cap additionally shaped by the domain warm-up ramp |
| Credentials | Per-workspace provider secrets encrypted (Fernet, HKDF-derived key, `APP_SECRET_KEY_OLD` rotation path); write-validated per-provider field allowlist with https-only URLs whose hosts must not be (or resolve to) private/link-local/metadata addresses (SSRF defense-in-depth; resolved at save time, redirects disabled on the shared client); never rendered back in the UI. One deliberate exception: the Africa's Talking **webhook URL token** (URL auth, not an API secret) is shown to admins in the registered-URL list — without it the webhook could never be registered |
| PII deletion | `POST /prospects/{id}/delete` (admin) erases the prospect and their messages/drafts/bookings while keeping the suppression entry (the lawful basis for honoring the opt-out) |
| Cost tracking | Real per-model pricing on every LLM call, stored where it is incurred (compose+judge on the Draft, reply-agent cost on the reply Draft), aggregated in Analytics and the kill-switch |
| Audit trail | Login success/failure, setup, campaign status, approvals/bulk-approve, credential & model changes, kill-switch pauses, job retries, PII deletions |

## 2b. The two dashboards

The product ships two equivalent operator UIs against the same backend:

- **Server-rendered** (Jinja2, zero JavaScript) at `/` — no build step,
  works everywhere, the reference implementation.
- **Next.js** (React/TypeScript) at `/app` — a static export mounted
  same-origin by FastAPI, so sessions and CSRF are identical. It reads from
  the `/api/v1/*` JSON endpoints and writes through the *same* form routes
  as the server-rendered UI (FormData + the csrf_token from `/api/v1/me`),
  so validation, audit logging, and permissions exist exactly once. Extras
  over the server-rendered UI: live-polling approvals/jobs pages,
  per-field credential forms (no hand-typed JSON), and per-campaign LLM
  cost columns.

Build it with `cd frontend && npm ci && npm run build` (output lands in
`frontend/out`, which the app auto-mounts when present — both the Render
buildCommand and the Dockerfile do this). For frontend development,
`npm run dev` proxies API and write routes to the FastAPI dev server on
:8000. If `frontend/out` is absent the engine simply runs without `/app`.

## 3. Local development

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # 3.10+
pip install -r requirements.txt
cp .env.example .env                                     # fill ANTHROPIC_API_KEY etc.
python scripts/seed_demo_workspace.py --email you@example.com --password <pw>
uvicorn server:app --reload
# open http://localhost:8000 — log in, review Settings, activate the campaign
```

SQLite is used automatically in dev (schema auto-created). Tests and lint:

```bash
pip install pytest pytest-asyncio ruff
pytest tests/ -q          # auth, CSRF, tenancy, webhooks, queue, pipeline, ops
ruff check engine tests server.py worker.py
# Run the suite against real Postgres (what CI does):
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname pytest tests/ -q
```

## 4. Production deployment (Render)

`render.yaml` provisions a Postgres database, the **web** service, and a
dedicated **worker** service (job queue + scheduler), runs `alembic upgrade
head` before each deploy, and generates `APP_SECRET_KEY`, `SETUP_TOKEN`, and
`METRICS_TOKEN`. Driverless `postgresql://` URLs from the platform are
normalized automatically (asyncpg for the app, psycopg2 for Alembic). A
`Dockerfile` is provided for non-Render targets. Dependencies are pinned and
constrained by `requirements.lock`.

The app **refuses to boot** in production with unsafe config: dev/short
`APP_SECRET_KEY`, SQLite `DATABASE_URL`, localhost/http `BASE_URL`, or a
missing sink while `LIVE_MODE=false`.

After the first deploy:

1. Set `BASE_URL` to the public https URL (webhook + unsubscribe links
   depend on it — the app will not start without it).
2. Set `ANTHROPIC_API_KEY`, `SINK_EMAIL`, `SINK_PHONE`, and ideally
   `SENTRY_DSN`.
3. Open the app → `/setup` creates the first workspace + admin (one-shot,
   requires the generated `SETUP_TOKEN` from the Render dashboard).
4. In **Settings**: fill the playbook, sending identity (a *verified* Resend
   domain — never a shared sandbox sender), provider credentials, and register
   the listed webhook URLs in each provider dashboard with their signing
   secrets.
5. Create a campaign, import a prospect CSV, activate.

Notes:
- Use paid instances in production — the free tier spins down, which stops
  the worker/scheduler and delays webhook handling (nothing is lost: state is
  in Postgres and jobs resume on wake — but follow-ups and sends stall).
- Horizontal scaling is safe on both tiers: job claiming uses `SELECT … FOR
  UPDATE SKIP LOCKED`, and the scheduler takes a Postgres advisory lock per
  pass, so extra replicas never run concurrent passes.
- Shutdown is graceful: SIGTERM stops the loops, in-flight jobs get a drain
  window (`SHUTDOWN_GRACE_SECONDS`), and anything cancelled mid-job is
  requeued immediately without burning a retry attempt.
- Database migrations: `alembic revision --autogenerate -m "…"` after model
  changes. CI applies migrations to fresh SQLite **and Postgres** databases
  and runs `alembic check` so a forgotten migration fails the build.
- `/health` is a real readiness check (DB ping + worker/scheduler heartbeat
  staleness); `/health/live` is bare liveness; `/metrics` serves Prometheus
  text metrics behind `METRICS_TOKEN`. Because the web tier's `/health`
  cannot see the separate worker process, `/metrics` exposes DB-derived
  queue lag — `engine_jobs_runnable` and
  `engine_jobs_oldest_runnable_age_seconds` — which is the signal to alert
  on for a dead or wedged worker (a healthy worker keeps the age near
  zero). Logs are JSON in production with a per-request `X-Request-ID`
  correlation id.
- Retention: done/dead jobs, webhook-event ledger rows, expired sessions,
  and old daily counters are purged daily on configurable windows
  (`RETENTION_*` env vars).

## 5. Go-live checklist (before `LIVE_MODE=true`)

- [ ] Sending domain verified in Resend; SPF/DKIM/DMARC green; warm-up plan
      for volume (start ≪ the 200/day cap).
- [ ] Unsubscribe link verified end-to-end on a staging prospect.
- [ ] Webhook signatures verified against each provider (send a test event).
- [ ] Kill-switch thresholds reviewed per workspace (Settings → stored on the
      workspace; defaults in env).
- [ ] Approval mode ON for every campaign until judge scores are trusted.
- [ ] Reply approval ON (the default) until the reply agent's answers are
      trusted — and note escalated replies are held even after opting into
      auto-send.
- [ ] Sink-mode dry run: a full campaign against the staff sink, reviewing
      drafts, judge scores, and the reply agent's answers.
- [ ] Data-handling sign-off from the client (this replaces the challenge-week
      "staff approval" rule).

## 6. Operations runbook

| Symptom | Where to look | Likely fix |
|---|---|---|
| Outbound stopped for a workspace | Banner on every page; Settings shows pause reason; audit log `killswitch_pause` | Investigate the breached metric in Analytics; resume in Settings |
| Draft stuck in "approved" | **Jobs page** (`/jobs`): `send_draft` row `failed`/`dead` with its error | Fix the cause (credentials, Resend outage); click **Retry** |
| Whole pipeline silent | `/health` returns 503 with the failing check named; `/metrics` `engine_jobs_oldest_runnable_age_seconds` climbing means the worker service is dead or wedged even while the web tier's `/health` is green | Restart the worker service; stuck `running` jobs are reaped automatically every scheduler pass |
| Webhook 401s | Provider dashboard delivery logs | Signing secret mismatch — re-save credentials; AT: token in URL must match; Svix: check clock skew (±5 min tolerance) |
| Replies not answered | `inbound_message` jobs on `/jobs`; prospect timeline shows inbound with no outbound | Check Anthropic key/credit; job retries automatically |
| Emails in spam | — | Verified domain, warm-up, lower daily cap; check bounce rate in Analytics |

Dead jobs (`status='dead'`) keep their full traceback and never re-run on
their own; a red banner on every dashboard page counts them, and the
transition to dead is logged at **error** level (so log-based alerting and
Sentry fire). Deterministic model failures (a refusal, output truncated at
`max_tokens`) dead-letter on the first attempt instead of re-billing the
same prompt five times. Requeue dead jobs from the **Jobs** page (resets
the attempt budget) after fixing the cause. Every failure is also in the
JSON logs (searchable by `request_id`) and in Sentry when `SENTRY_DSN` is
set.

## 7. Extension points

- **Enrichment source** (contract wired; bring a live provider):
  `Prospect.signals` is the contract — a JSON object of named signals with
  `confidence`. Point the workspace `enrichment` credential at any endpoint
  implementing `POST {email, name, company, title, phone} → {"signals":
  {...}, "icp_segment": 1-4}` (https to a public host; http://localhost in
  dev). The Week-10 challenge pipeline ships serving exactly that shape
  (`ENRICHMENT_API_KEY=<key> uvicorn enrichment.service:app --port 8100` —
  Crunchbase ODM sample + layoffs.fyi + job-post velocity + AI-maturity
  scoring + ICP classification + the **competitor gap brief**), but note:
  **several of its sub-signals are deterministic proxies, not live
  lookups**. It therefore declares `"synthetic": true` in its responses,
  and the engine hard-gates that: synthetic-flagged signals always compose
  in inquiry mode (never assertion), and the research-finding opener is
  suppressed. For assertion-mode outreach, connect a real provider
  (Clay/Apollo-style wrapper or an internal service) that returns verified
  signals without the flag. CSV rows with a `signals` column and the
  per-prospect signals editor keep working as manual sources.
- **Market-space map** (stretch deliverable): `scripts/build_market_space.py`
  clusters the full ODM sample into sector × size × AI-readiness cells scored
  for bench match — outputs `market_space.csv` / `top_cells.md`, with proxy
  limitations documented in `market_space_methodology.md`.
- **WhatsApp cold outbound**: the conversational WhatsApp channel is live
  (inbound + replies via Twilio); adding template-based cold touches means
  registering Meta-approved templates and a `whatsapp` campaign channel —
  suppression, caps, and sink mode already handle the channel.
- **Fine-tuned judge**: `engine/services/judge.py` is the seam; the
  Settings → judge fine-tuning export produces the labeled training data,
  and the Week-11 LoRA critic swaps in behind the same `judge_draft()`
  signature (serve it via `JUDGE_MODEL=local:<name>`).
- **Voice**: TwiML endpoints are live (signature-verified); outbound dialing
  can be added as a job type.

## 8. Repository layout

```
engine/            product package (see engine/__init__.py for the map)
migrations/        Alembic (schema + index migrations committed)
tests/             pytest suite (offline — providers mocked; runs on SQLite
                   and, via TEST_DATABASE_URL, on Postgres)
server.py, app.py  web entry points (identical)
worker.py          standalone worker/scheduler process (python -m worker)
Dockerfile         container build (web by default; worker via command)
requirements.lock  fully pinned transitive dependency set
scripts/seed_demo_workspace.py   one-command demo workspace
render.yaml        Render blueprint (Postgres + web + worker + migrations)
.github/workflows/ci.yml   lint + SQLite & Postgres migration/drift checks
                   + tests on both dialects + dependency CVE audit

# Research / challenge coursework (kept intact, not part of the product):
agent/ enrichment/ eval/ probes/ mechanism/ tenacious_bench_v0.1/ training/ …
demo_ui.py         superseded by the real dashboard (kept as an artifact)
```

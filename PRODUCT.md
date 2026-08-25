# Conversion Engine — Product & Operations Guide

Multi-tenant AI outbound conversion platform: signal-grounded email outreach
composed by Claude, gated by an LLM judge and human approval, with a
conversational reply agent, SMS handoff, Cal.com booking, HubSpot sync, and a
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
   ≥ `auto_approve_score` go straight to send. Bulk approve is available.
5. **send_draft** job: policy checks (workspace pause → suppression list →
   touch ceiling → daily cap), then Resend send with a per-prospect
   unsubscribe link and RFC 8058 one-click unsubscribe headers. In sink mode
   the recipient is replaced by `SINK_EMAIL` with the intended recipient in a
   header.
6. **Follow-ups**: the campaign sequence (`[{day_offset, angle}, ...]`)
   schedules the next touch; any inbound reply cancels the sequence.

### The inbound pipeline

- **Email replies** arrive via the Resend inbound webhook. **SMS** arrives via
  Africa's Talking. STOP/START/HELP are handled synchronously (compliance);
  everything else is recorded on the prospect's timeline and queued.
- **inbound_message** job runs the reply agent (Claude, full conversation
  history, playbook-only facts): classifies intent (warm / question /
  objection / neutral / cold), drafts the channel-appropriate reply with the
  personalized Cal.com booking link, and flags escalations (pricing beyond
  public bands, legal, anger, out-of-playbook questions) to the dashboard.
- **Cold intent** → both channels suppressed, prospect → `opted_out`, no reply.
- **Cal.com webhook** (BOOKING_CREATED/CANCELLED/RESCHEDULED) records the
  booking, advances the prospect to `booked`, and queues the HubSpot update.

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
| Auth | DB-backed sessions (only the token hash is stored), bcrypt passwords, admin/operator roles, one-shot `/setup` bootstrap |
| Tenancy | `workspace_id` on every row; ownership re-checked on every mutating route |
| Webhooks | Fail closed. Svix (Resend), HMAC-SHA256 (Cal.com), Twilio request signing, secret URL token (Africa's Talking — it does not sign). No secret configured → requests rejected |
| Idempotency | `WebhookEvent` unique ledger per (provider, event id); job `idempotency_key` unique index; provider retries and double-clicks cannot double-send |
| Suppression | Durable DB table per (workspace, channel, address); written on STOP, unsubscribe click, bounce, complaint, cold intent, manual action; checked before **every** send. STOP confirmations bypass policy checks as required by carrier rules |
| Unsubscribe | Every email carries `List-Unsubscribe` + one-click POST + a visible link to `/u/{token}` |
| Sink mode | `LIVE_MODE=false` (default) reroutes all outbound to `SINK_EMAIL`/`SINK_PHONE`. Missing sink → send refused, never silently delivered |
| Kill-switch | Rolling 7-day opt-out rate, bounce rate, cost per qualified lead (with a 20-send floor so tiny samples can't trip it). Breach → workspace outbound paused + audit log; admin reviews and resumes in Settings |
| Volume caps | Per-workspace daily email/SMS caps and a per-prospect touch ceiling (default 4) |
| Credentials | Per-workspace provider secrets encrypted (Fernet, key derived from `APP_SECRET_KEY`); never rendered back in the UI |
| Cost tracking | Real per-model pricing on every LLM call, stored per message, aggregated in Analytics |

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
pytest tests/ -q          # 39 tests: auth, tenancy, webhooks, queue, pipeline
ruff check engine tests server.py
```

## 4. Production deployment (Render)

`render.yaml` provisions a Postgres database and the web service, runs
`alembic upgrade head` before each deploy, and generates `APP_SECRET_KEY`.
After the first deploy:

1. Set `BASE_URL` to the public URL (webhook + unsubscribe links depend on it).
2. Set `ANTHROPIC_API_KEY`, `SINK_EMAIL`, `SINK_PHONE`.
3. Open the app → `/setup` creates the first workspace + admin (one-shot).
4. In **Settings**: fill the playbook, sending identity (a *verified* Resend
   domain — never a shared sandbox sender), provider credentials, and register
   the listed webhook URLs in each provider dashboard with their signing
   secrets.
5. Create a campaign, import a prospect CSV, activate.

Notes:
- Use the paid instance in production — the free tier spins down, which stops
  the worker/scheduler and delays webhook handling (nothing is lost: state is
  in Postgres and jobs resume on wake — but follow-ups and sends stall).
- Horizontal scaling is safe: job claiming uses `SELECT … FOR UPDATE SKIP
  LOCKED`; the scheduler's actions are idempotent. To split roles, run a
  second service with `RUN_WORKER=true` and set `RUN_WORKER=false` on web.
- Database migrations: `alembic revision --autogenerate -m "…"` after model
  changes; CI applies migrations to a fresh DB to catch drift.

## 5. Go-live checklist (before `LIVE_MODE=true`)

- [ ] Sending domain verified in Resend; SPF/DKIM/DMARC green; warm-up plan
      for volume (start ≪ the 200/day cap).
- [ ] Unsubscribe link verified end-to-end on a staging prospect.
- [ ] Webhook signatures verified against each provider (send a test event).
- [ ] Kill-switch thresholds reviewed per workspace (Settings → stored on the
      workspace; defaults in env).
- [ ] Approval mode ON for every campaign until judge scores are trusted.
- [ ] Sink-mode dry run: a full campaign against the staff sink, reviewing
      drafts, judge scores, and the reply agent's answers.
- [ ] Data-handling sign-off from the client (this replaces the challenge-week
      "staff approval" rule).

## 6. Operations runbook

| Symptom | Where to look | Likely fix |
|---|---|---|
| Outbound stopped for a workspace | Banner on every page; Settings shows pause reason; audit log `killswitch_pause` | Investigate the breached metric in Analytics; resume in Settings |
| Draft stuck in "approved" | Jobs table: `send_draft` row `failed`/`dead` with `last_error` | Fix the cause (credentials, Resend outage); set status back to `failed` to retry |
| Webhook 401s | Provider dashboard delivery logs | Signing secret mismatch — re-save credentials; AT: token in URL must match |
| Replies not answered | `inbound_message` jobs; prospect timeline shows inbound with no outbound | Check Anthropic key/credit; job retries automatically |
| Emails in spam | — | Verified domain, warm-up, lower daily cap; check bounce rate in Analytics |

Dead jobs (`status='dead'`) keep their full traceback in `last_error` and
never re-run; requeue by setting `status='failed'` after fixing the cause.

## 7. Extension points

- **Live enrichment**: `Prospect.signals` is the contract — a JSON object of
  named signals with `confidence` (high/medium/low). Wire the existing
  `enrichment/` pipeline (or any source) to populate it and set
  `stage='enriched'`; nothing downstream changes.
- **WhatsApp channel**: add a sender in `engine/services/`, a webhook route,
  and a `channel` value — suppression, caps, and the reply agent are already
  channel-generic.
- **Fine-tuned judge**: `engine/services/judge.py` is the seam; swap the API
  judge for the Week-11 LoRA critic behind the same `judge_draft()` signature.
- **Voice**: TwiML endpoints are live (signature-verified); outbound dialing
  can be added as a job type.

## 8. Repository layout

```
engine/            product package (see engine/__init__.py for the map)
migrations/        Alembic (initial schema committed)
tests/             pytest suite (39 tests, all offline — providers mocked)
server.py, app.py  entry points (identical)
scripts/seed_demo_workspace.py   one-command demo workspace
render.yaml        Render blueprint (Postgres + web + migrations)
.github/workflows/ci.yml         lint + migration check + tests

# Research / challenge coursework (kept intact, not part of the product):
agent/ enrichment/ eval/ probes/ mechanism/ tenacious_bench_v0.1/ training/ …
demo_ui.py         superseded by the real dashboard (kept as an artifact)
```

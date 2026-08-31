# Runbook

Operational procedures for the Conversion Engine. Written for whoever is
on call at 3am, not for the person who wrote the code.

**Topology:** two Render services against one Postgres.
`conversion-engine` (web: dashboard, webhooks — `RUN_WORKER=false`) and
`conversion-engine-worker` (job queue + scheduler — `RUN_WORKER=true`).
Both read the same `DATABASE_URL` and must share `APP_SECRET_KEY`.

---

## 1. Stop the bleeding

Anything that sends is gated by two switches. Reach for these before
debugging.

### Stop one tenant

Dashboard → **Settings → Pause outbound**, or:

```sql
UPDATE workspaces SET outbound_paused = true,
       pause_reason = 'incident <ref>' WHERE slug = '<slug>';
```

Takes effect on the next job — no deploy needed. `check_can_send()`
refuses every outbound while it is set. Resume from Settings → Resume
outbound (which also clears `pause_reason`).

### Stop the whole platform

Set `LIVE_MODE=false` on **both** services and restart. Every send is
redirected to `SINK_EMAIL` / `SINK_PHONE` with a `[SINK — intended for …]`
prefix. The pipeline keeps running and stays observable; nothing reaches a
real recipient.

If it must stop entirely, scale `conversion-engine-worker` to 0. The web
tier keeps serving the dashboard and keeps accepting webhooks (inbound
replies and opt-outs are still recorded — **do not** scale the web tier to
zero during an incident, or you will silently drop STOP requests).

---

## 2. Triage

```bash
curl -s https://<host>/health | jq          # DB + worker + scheduler
curl -s https://<host>/health/live          # process only, no deps
curl -s -H "Authorization: Bearer $METRICS_TOKEN" https://<host>/metrics
```

`/health` returns **503** when the database is unreachable or, on an
instance that runs them, the worker or scheduler heartbeat is stale. On the
web service (`RUN_WORKER=false`) it only checks the database — a green web
`/health` says nothing about the worker. Judge the worker by queue depth:

| Metric | Meaning | Investigate when |
|---|---|---|
| `engine_jobs_runnable` | claimable now | rising steadily |
| `engine_jobs_oldest_runnable_age_seconds` | queue lag | > ~600 |
| `engine_jobs_total{status="dead"}` | exhausted retries | any increase |
| `engine_workspaces_paused` | kill-switch trips | unexpected non-zero |

Logs are JSON, one object per line, with `request_id` on every line emitted
while handling a request. To follow one request end to end, filter on it.
Errors also go to Sentry when `SENTRY_DSN` is set.

---

## 3. Common incidents

### Queue lag climbing / nothing sending

1. Is the worker alive? Check its logs for the `worker_loop` heartbeat.
2. `engine_jobs_total{status="running"}` high and static → jobs are wedged.
   The reaper requeues anything `running` longer than
   `JOB_STUCK_AFTER_MINUTES` (default 45). **Do not lower this below the
   worst-case job runtime** — a compose job makes up to four LLM calls, and
   reaping early duplicates drafts and doubles spend.
3. Still stuck → restart the worker. Claiming uses `SKIP LOCKED`, so an
   interrupted job is safely re-claimed after the reaper window.

```sql
SELECT type, status, count(*) FROM jobs GROUP BY 1, 2 ORDER BY 3 DESC;
SELECT id, type, attempts, last_error FROM jobs
 WHERE status = 'dead' ORDER BY updated_at DESC LIMIT 20;
```

### Dead-lettered jobs

`status='dead'` means retries were exhausted. Read `last_error` first —
most are permanent (invalid recipient, revoked token) and must not be
replayed blind. To retry after fixing the cause:

```sql
UPDATE jobs SET status = 'pending', attempts = 0, run_after = now()
 WHERE id = '<job id>';
```

### A tenant's sends are all blocked

In order of likelihood: `outbound_paused` set (kill-switch tripped — check
`pause_reason`); recipient on the suppression list; per-prospect touch
ceiling (`MAX_TOUCHES_PER_PROSPECT`, default 4) reached; daily cap hit; or
warm-up still ramping — a new sending domain is capped at
`WARMUP_START_PER_DAY` growing `WARMUP_DAILY_GROWTH`× per day, which is
**intended** and should not be raised to clear a backlog.

### Webhooks returning 401

Fail-closed is by design: a provider with no configured signing secret is
rejected, never processed unsigned. Check Settings → credentials for that
provider. After an `APP_SECRET_KEY` rotation done without
`APP_SECRET_KEY_OLD`, stored credentials cannot be decrypted — the log line
says so explicitly, and every tenant must re-enter their credentials.

### Kill-switch tripped

The scheduler pauses a workspace when its opt-out rate over
`KILLSWITCH_WINDOW_DAYS` exceeds `KILLSWITCH_OPT_OUT_RATE` (default 5% over
7 days). This is usually correct — treat a trip as a content problem, not a
false alarm. Read the recent messages before resuming; resuming without
changing the copy will trip it again and burn domain reputation.

---

## 3a. LLM tracing (Langfuse)

Tracing is **optional and fail-open**: with `LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY` unset it is inert, and when set it can never break a
send — a Langfuse outage, bad key or SDK error degrades to "no trace" and the
call proceeds. Do not debug a stalled pipeline by looking here first; check
queue depth (§2).

What it gives you that the database does not: the **prompt and response
bodies**. Spend is already tracked without it — `engine/services/llm.py`
computes per-call cost into `Draft.compose_cost_usd` and `Message.cost_usd`,
and the kill-switch reads those sums. Traces are for answering *why did this
draft read badly*, not *what did it cost*.

Traces are named by role — `compose`, `judge`, `reply` — and carry
`workspace_id`, `prospect_id` and the backend used. Cost is reported from the
engine's own figure, so the Langfuse dashboard reconciles with the kill-switch
ledger rather than quietly disagreeing with it.

**Privacy.** Traces contain full prompt and response bodies: prospect names,
companies, email addresses, message content. This deployment points at
Langfuse Cloud, so that data leaves your infrastructure — it is in scope for
any data-processing commitment you make to a client. To keep it in-house,
point `LANGFUSE_HOST` at a self-hosted instance; nothing else changes.

To turn tracing off in a hurry, clear both keys and restart. To cut volume
without losing it entirely, lower `LANGFUSE_SAMPLE_RATE`.

Buffered traces are flushed on shutdown. A `kill -9` loses the last batch —
traces are diagnostic, never a system of record.

## 4. Deploys and rollback

`preDeployCommand` runs `alembic upgrade head` before the new version goes
live, so **migrations must be backward compatible with the running
release** — additive columns, no destructive renames in the same deploy as
the code that stops using them.

Rollback: Render dashboard → the service → **Rollback** to the previous
deploy. This reverts code only, never the database. If the bad deploy
shipped a migration:

1. Roll the code back first.
2. Only then decide about the schema. `alembic downgrade -1` is a last
   resort and is not safe for a migration that dropped or rewrote data.
3. Prefer rolling *forward* with a corrective migration.

Roll web and worker back together — they share models and a schema.

### Verifying a deploy

```bash
curl -s https://<host>/health | jq -e '.status == "ok"'
```

Then confirm `engine_jobs_oldest_runnable_age_seconds` is not climbing.

---

## 5. Backups and restore

Render's managed Postgres takes automatic daily backups with
point-in-time recovery on paid plans; retention follows the plan. Restore
via Render dashboard → the database → Backups → Restore, which provisions a
**new** instance.

To restore:

1. Pause outbound on all tenants (or set `LIVE_MODE=false`) **first** —
   restoring re-animates jobs that were pending at snapshot time, and they
   will send on resume.
2. Restore to a new instance and verify: `SELECT count(*) FROM workspaces;`
   and `SELECT max(created_at) FROM messages;`
3. Point `DATABASE_URL` on both services at the new instance.
4. `alembic upgrade head` (the snapshot may predate the current schema).
5. Sweep the queue before resuming — anything old enough to be irrelevant
   should be killed rather than sent:
   ```sql
   UPDATE jobs SET status = 'dead', last_error = 'stale after restore'
    WHERE status = 'pending' AND run_after < now() - interval '1 day';
   ```
6. Resume outbound.

**`APP_SECRET_KEY` is not in the database backup.** Tenant credentials are
encrypted with it, so a restore without the original key leaves every
credential undecryptable. Keep it in a password manager; losing it means
every tenant re-enters every credential.

**Verify quarterly.** A backup you have never restored is a hypothesis.

---

## 5a. First deploy (Render)

Getting it *running*. Going live — actually mailing a prospect — is §6, and
they are deliberately separate steps.

### Before you click deploy

Two decisions, neither reversible for free:

**Plan.** `render.yaml` specifies `starter` web + `starter` worker +
`basic-1gb` Postgres. Background workers are not on Render's free tier, and a
free web service spins down when idle — a spun-down service runs no worker
loop, so scheduled follow-ups never fire. Free tier is fine for proving the
deploy works by hand; it cannot run the pipeline unattended.

**One service or two.** The blueprint runs web and worker separately so a slow
LLM job cannot stall webhook handling. To collapse to one (cheaper, less
robust), delete the worker service and set `RUN_WORKER=true` on web.

### Free-tier variant

`render-free.yaml` deploys one service on Render's free plan with an external
free Postgres (Neon — `engine/db.py` normalises its connection string as
given). Background Workers are not on the free tier, so that service runs the
queue in-process, and migrations move into `startCommand` because
`preDeployCommand` is a paid feature.

It is for demos and evaluation. A free web service spins down after ~15
minutes idle, and a spun-down service runs no worker loop — scheduled
follow-ups will not fire while it sleeps. Everything can be driven by hand;
nothing can be left running.

### Deploy

1. Push the branch and point Render's blueprint at it (or merge to `main`).
2. Create from `render.yaml`. It provisions Postgres and both services, and
   generates `APP_SECRET_KEY`, `SETUP_TOKEN`, `METRICS_TOKEN`.
3. Set the `sync: false` values on **both** services: `BASE_URL` (the public
   https URL — the app refuses to boot on http or localhost),
   `ANTHROPIC_API_KEY`, `SINK_EMAIL`, `SINK_PHONE`, and optionally
   `SENTRY_DSN` / `LANGFUSE_*`.
4. **Copy `APP_SECRET_KEY` into a password manager now.** It encrypts every
   tenant credential and is not in database backups (§5).

`preDeployCommand` runs `alembic upgrade head` before the new version goes
live, so migrations apply on their own.

### Verify, in this order

```bash
curl -s https://<host>/health | jq          # database reachable
curl -s https://<host>/app/ -o /dev/null -w '%{http_code}\n'   # dashboard built
```

A green web `/health` says nothing about the worker — it only checks the
database when `RUN_WORKER=false`. Judge the worker by its logs
(`worker_loop` heartbeat) and by queue depth staying flat (§2).

### Bootstrap the workspace

5. Read `SETUP_TOKEN` from the Render dashboard, visit `/setup`, create the
   admin. Without the token `/setup` refuses in production, which is what
   stops the first passer-by becoming admin on a fresh database.
6. Re-enter provider credentials in Settings. **They do not travel** — local
   credentials live in local SQLite; production has its own Postgres.
7. Register the webhooks, now that `BASE_URL` is public:
   ```bash
   python scripts/setup_telegram_webhook.py --slug <slug>
   python scripts/setup_calcom_webhook.py --slug <slug>
   ```
   Resend's is created in its dashboard (or via its API); store the signing
   secret in Settings. Every provider fails closed, so an unregistered or
   mis-secreted webhook means inbound replies silently do nothing.
8. Delete any webhook still pointing at an old tunnel URL — a stale
   subscriber is the usual reason "nothing happens" after a redeploy.

### Smoke test before §6

With `LIVE_MODE=false`, activate a campaign and let one draft run end to end.
Everything reaches `SINK_EMAIL` instead of a prospect, so this exercises the
real credentials, the queue, compose, judge and send without touching anyone.
Only then move to §6.

---

## 6. Going live (first real send)

The system ships with `LIVE_MODE=false` — it has never sent to a real
recipient. Cross this deliberately, once, with a named owner.

1. **Confirm sink mode works end to end.** Run a full sequence and read the
   `[SINK — intended for …]` messages. Everything below assumes this passed.
2. **Sender authentication.** SPF, DKIM and DMARC on the sending domain.
   Skip this and the first campaign trains spam filters against you.
3. **Provider accounts off sandbox.** Africa's Talking sandbox only
   delivers to registered testers; Twilio trial only to verified numbers.
4. **Register webhooks** against the public HTTPS URL — Resend, Cal.com,
   Twilio, Telegram (`scripts/setup_telegram_webhook.py`,
   `scripts/setup_calcom_webhook.py`) — and store each signing secret in
   Settings. Unconfigured providers fail closed.
5. **Verify the opt-out path before the first send, not after.** Send
   yourself a real message, click the unsubscribe link, confirm the
   suppression row exists and a follow-up is refused. This is the one path
   with legal consequences and no undo.
6. **Set conservative caps.** Leave warm-up on. Start with one workspace
   and a small list.
7. **Flip `LIVE_MODE=true` on both services** and restart.
8. **Watch for the first hour**: `engine_jobs_total{status="dead"}`,
   opt-out rate, bounces. Bounces above a few percent — stop and fix the
   list, do not push through.

Roll back by setting `LIVE_MODE=false` and restarting. Messages already
handed to a provider cannot be recalled.

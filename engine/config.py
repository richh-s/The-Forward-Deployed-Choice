"""Application settings.

Every deploy-time knob lives here, loaded from the environment (and .env in
development). Nothing else in the codebase reads os.environ directly — that
keeps missing-config failures at startup, in one place, with a clear error.

In production the model_validator below fails fast on unsafe values instead
of booting with defaults that silently misbehave (localhost unsubscribe
links, SQLite on ephemeral disk, a guessable secret key).
"""
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── core ──────────────────────────────────────────────────────────
    app_name: str = "Tenacious Conversion Engine"
    environment: str = Field(default="development")  # development | production
    base_url: str = Field(default="http://localhost:8000")
    # Secret for tenant-credential encryption and CSRF token derivation.
    # MUST be set to a long random value (>= 32 chars) in production.
    app_secret_key: str = Field(default="dev-secret-change-me")
    # Previous secret during rotation: credentials encrypted under it are
    # still decryptable and get re-encrypted under app_secret_key on write.
    app_secret_key_old: str = Field(default="")
    # Required to run /setup in production (one-shot bootstrap guard).
    setup_token: str = Field(default="")

    # ── database ──────────────────────────────────────────────────────
    # e.g. postgresql+asyncpg://user:pass@host:5432/dbname — bare
    # postgres:// URLs (Render/Heroku) are normalized automatically.
    database_url: str = Field(default="sqlite+aiosqlite:///./engine.db")
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800
    db_pool_timeout_seconds: int = 30
    db_statement_timeout_ms: int = 60_000

    # ── LLM (platform-level; per-workspace overrides live in the DB) ──
    anthropic_api_key: str = Field(default="")
    # Required only for identity-linked API keys, which must declare the
    # Anthropic workspace a request acts in. Ordinary keys ignore it.
    anthropic_workspace_id: str = Field(default="")
    compose_model: str = Field(default="claude-opus-5")
    reply_model: str = Field(default="claude-opus-5")
    # Prefix a model with "local:" to serve it from LOCAL_LLM_BASE_URL
    # (OpenAI-compatible; e.g. JUDGE_MODEL=local:qwen2.5:14b).
    judge_model: str = Field(default="claude-opus-5")
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3

    # Self-hosted models (Ollama / LM Studio / vLLM / llama.cpp) reachable
    # over the private network (e.g. Tailscale MagicDNS):
    #   http://<machine>.<tailnet>.ts.net:11434/v1
    local_llm_base_url: str = Field(default="")
    local_llm_api_key: str = Field(default="")
    # Reasoning models spend tokens thinking before answering; floor the
    # output budget for local calls so JSON isn't truncated.
    local_llm_min_max_tokens: int = 4096
    # Local reasoning models are slower than the hosted API — give them their
    # own timeout so the Anthropic timeout can stay tight.
    local_llm_timeout_seconds: float = 180.0

    # ── worker ────────────────────────────────────────────────────────
    run_worker: bool = Field(default=True)  # in-process worker loop
    worker_poll_seconds: float = 2.0
    # Concurrent job slots per process (forced to 1 on SQLite).
    worker_concurrency: int = 4
    scheduler_interval_seconds: float = 60.0
    job_max_attempts: int = 5
    # Jobs stuck in 'running' longer than this are requeued by the reaper.
    # Must exceed the worst-case job runtime: a compose job can make four
    # LLM calls (compose, judge, regenerate, re-judge), each with SDK-level
    # timeouts and retries — reaping too early duplicates drafts and spend.
    job_stuck_after_minutes: int = 45
    # Worker drain window on shutdown before in-flight jobs are cancelled.
    shutdown_grace_seconds: float = 20.0

    # ── retention (days; 0 disables that purge) ──────────────────────
    retention_done_jobs_days: int = 30
    retention_dead_jobs_days: int = 90
    retention_webhook_events_days: int = 30
    retention_daily_counters_days: int = 90

    # ── outbound safety rails (platform-wide hard ceilings) ──────────
    live_mode: bool = Field(default=False)  # False → all outbound to sink
    sink_email: str = Field(default="")     # staff sink address when not live
    sink_phone: str = Field(default="")
    max_emails_per_day_per_workspace: int = 200
    max_sms_per_day_per_workspace: int = 200
    max_whatsapp_per_day_per_workspace: int = 200
    max_touches_per_prospect: int = 4

    # ── deliverability warm-up (email) ───────────────────────────────
    # New sending domains must ramp, not blast: the effective email cap is
    # min(daily cap, warmup_start_per_day * warmup_daily_growth^days) where
    # days counts from the workspace's first outbound email.
    warmup_enabled: bool = True
    warmup_start_per_day: int = 20
    warmup_daily_growth: float = 1.25

    # ── weekly client digest ─────────────────────────────────────────
    weekly_digest_enabled: bool = True

    # ── kill-switch defaults (per-workspace overrides in DB) ─────────
    killswitch_window_days: int = 7
    killswitch_opt_out_rate: float = 0.05
    killswitch_bounce_rate: float = 0.05
    killswitch_cost_per_qualified_lead_usd: float = 8.0
    # Absolute LLM spend ceiling over the window — trips even when the
    # workspace has zero qualified leads (the runaway-spend case).
    killswitch_max_llm_cost_usd: float = 100.0

    # ── rate limiting (per process) ───────────────────────────────────
    login_rate_limit_attempts: int = 5      # per window, per IP+email
    login_rate_limit_window_seconds: int = 300
    public_rate_limit_requests: int = 30    # /u/* and /setup, per IP
    public_rate_limit_window_seconds: int = 60
    # Reject request bodies larger than this on non-upload routes.
    max_body_bytes: int = 1_048_576

    # ── observability ────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="")     # "json" | "text"; json in prod
    sentry_dsn: str = Field(default="")
    # Optional bearer token protecting GET /metrics (open when empty and
    # not in production; in production an empty token disables /metrics).
    metrics_token: str = Field(default="")

    # ── session auth ─────────────────────────────────────────────────
    session_ttl_hours: int = 24 * 7
    # Hard cap on total session age: sliding renewal never extends a session
    # past created_at + this, so a stolen cookie cannot live forever.
    session_absolute_hours: int = 24 * 30
    session_cookie_name: str = "engine_session"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def resolved_log_format(self) -> str:
        if self.log_format in ("json", "text"):
            return self.log_format
        return "json" if self.is_production else "text"

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.environment not in ("development", "production", "test"):
            raise ValueError(
                f"ENVIRONMENT must be development|production|test, "
                f"got {self.environment!r}"
            )
        if not self.is_production:
            return self
        problems: list[str] = []
        if self.app_secret_key == "dev-secret-change-me":
            problems.append("APP_SECRET_KEY is still the dev default")
        if len(self.app_secret_key) < 32:
            problems.append("APP_SECRET_KEY must be at least 32 characters")
        if self.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL points at SQLite — data would live on "
                "ephemeral disk; set a Postgres URL"
            )
        if self.base_url.rstrip("/") in (
            "http://localhost:8000", "http://127.0.0.1:8000", ""
        ):
            problems.append(
                "BASE_URL is unset/localhost — unsubscribe and webhook "
                "links would be wrong; set the public URL"
            )
        if self.base_url.startswith("http://"):
            problems.append("BASE_URL must be https:// in production")
        if not self.live_mode and not self.sink_email:
            problems.append(
                "LIVE_MODE is off but SINK_EMAIL is unset — every email "
                "send would be refused"
            )
        if problems:
            raise ValueError(
                "Refusing to start with unsafe production config:\n  - "
                + "\n  - ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

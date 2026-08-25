"""Application settings.

Every deploy-time knob lives here, loaded from the environment (and .env in
development). Nothing else in the codebase reads os.environ directly — that
keeps missing-config failures at startup, in one place, with a clear error.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── core ──────────────────────────────────────────────────────────
    app_name: str = "Tenacious Conversion Engine"
    environment: str = Field(default="development")  # development | production
    base_url: str = Field(default="http://localhost:8000")
    # Secret for session signing and tenant-credential encryption.
    # MUST be set to a long random value in production.
    app_secret_key: str = Field(default="dev-secret-change-me")

    # ── database ──────────────────────────────────────────────────────
    # e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = Field(default="sqlite+aiosqlite:///./engine.db")

    # ── LLM (platform-level; per-workspace overrides live in the DB) ──
    anthropic_api_key: str = Field(default="")
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
    scheduler_interval_seconds: float = 60.0
    job_max_attempts: int = 5

    # ── outbound safety rails (platform-wide hard ceilings) ──────────
    live_mode: bool = Field(default=False)  # False → all outbound to sink
    sink_email: str = Field(default="")     # staff sink address when not live
    sink_phone: str = Field(default="")
    max_emails_per_day_per_workspace: int = 200
    max_sms_per_day_per_workspace: int = 200
    max_touches_per_prospect: int = 4

    # ── kill-switch defaults (per-workspace overrides in DB) ─────────
    killswitch_window_days: int = 7
    killswitch_opt_out_rate: float = 0.05
    killswitch_bounce_rate: float = 0.05
    killswitch_cost_per_qualified_lead_usd: float = 8.0

    # ── observability ────────────────────────────────────────────────
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    langfuse_host: str = Field(default="https://cloud.langfuse.com")
    log_level: str = Field(default="INFO")

    # ── session auth ─────────────────────────────────────────────────
    session_ttl_hours: int = 24 * 7
    session_cookie_name: str = "engine_session"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

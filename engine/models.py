"""ORM models.

Multi-tenancy: every business entity carries a workspace_id and every query
in routes/services filters on it. Types are kept portable (String/Text/JSON)
so the same models run on Postgres in production and SQLite in tests.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_aware(dt: datetime | None) -> datetime | None:
    """Coerce a DB-loaded datetime to aware-UTC (SQLite drops tzinfo)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ── tenancy ───────────────────────────────────────────────────────────


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    # Operational state
    outbound_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(400))

    # Playbook: company profile, value prop, tone, ICP definition, templates.
    # Editable in Settings; consumed by the composer and reply agent.
    playbook: Mapped[dict] = mapped_column(JSON, default=dict)

    # Sending identity
    from_email: Mapped[str | None] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(200))
    sms_sender_id: Mapped[str | None] = mapped_column(String(20))
    calcom_event_url: Mapped[str | None] = mapped_column(String(500))

    # Kill-switch threshold overrides (fall back to platform defaults)
    killswitch: Mapped[dict] = mapped_column(JSON, default=dict)

    # Hold reply-agent responses for human review before sending (escalated
    # replies are always held regardless of this flag).
    require_reply_approval: Mapped[bool] = mapped_column(Boolean, default=True)

    # Per-workspace model overrides by role: {"compose": "...", "reply":
    # "...", "judge": "local:gemma-4-26b"}. Empty → platform env defaults.
    llm_config: Mapped[dict] = mapped_column(JSON, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="workspace")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="operator")  # admin|operator
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set on admin-created accounts and password resets: the user must pick
    # their own password before doing anything else.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="users")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    # Stores a hash of the session token, never the token itself.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceCredential(Base, TimestampMixin):
    """Per-tenant provider credentials, encrypted at rest with the app key."""

    __tablename__ = "workspace_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", name="uq_cred_ws_provider"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    # resend | hubspot | calcom | africastalking | twilio | anthropic
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    # Webhook signing secrets are stored here too (part of the payload).


# ── prospects & campaigns ─────────────────────────────────────────────

PROSPECT_STAGES = [
    "new", "enriched", "queued", "contacted", "replied",
    "warm", "booked", "lost", "opted_out",
]


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|active|paused|completed
    # Per-campaign playbook overrides (angle, template hints, mode override)
    playbook: Mapped[dict] = mapped_column(JSON, default=dict)
    daily_cap: Mapped[int] = mapped_column(Integer, default=50)
    # Follow-up sequence: [{"day_offset": 3, "angle": "..."}, ...]
    sequence: Mapped[list] = mapped_column(JSON, default=list)
    # Require human approval for drafts (vs auto-approve above threshold)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_approve_score: Mapped[float] = mapped_column(Float, default=0.9)
    send_window_start_hour: Mapped[int] = mapped_column(Integer, default=8)
    send_window_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")


class Prospect(Base, TimestampMixin):
    __tablename__ = "prospects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_prospect_ws_email"),
        Index("ix_prospects_ws_stage", "workspace_id", "stage"),
        # Scheduler scans per campaign for new prospects and due follow-ups.
        Index("ix_prospects_campaign_stage", "campaign_id", "stage"),
        Index("ix_prospects_followup", "campaign_id", "next_followup_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164
    name: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")

    stage: Mapped[str] = mapped_column(String(20), default="new")
    icp_segment: Mapped[int | None] = mapped_column(Integer)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)  # enrichment output
    avg_confidence: Mapped[float | None] = mapped_column(Float)

    # Sequencing state
    touch_count: Mapped[int] = mapped_column(Integer, default=0)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Telegram chat linked to this prospect (set when they /start the
    # workspace bot with their deep-link payload); the conversational
    # Telegram channel routes through it.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32), index=True)

    # Per-prospect unsubscribe token embedded in every email
    unsubscribe_token: Mapped[str] = mapped_column(
        String(32), default=new_id, unique=True
    )
    hubspot_contact_id: Mapped[str | None] = mapped_column(String(40))


class Draft(Base, TimestampMixin):
    """AI-composed outbound message awaiting review (the approval queue)."""

    __tablename__ = "drafts"
    __table_args__ = (Index("ix_drafts_ws_status", "workspace_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"))
    # outreach: campaign-composed first/follow-up touch (judged, sequenced).
    # reply: reply-agent response to an inbound message (no judge score;
    # sending never advances the touch/follow-up sequence).
    kind: Mapped[str] = mapped_column(String(10), default="outreach")
    channel: Mapped[str] = mapped_column(String(10), default="email")  # email|sms
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="")  # assertion|inquiry
    # Campaign angle this draft was composed with — the attribution key for
    # the learning loop (which angles earn replies/bookings).
    angle: Mapped[str] = mapped_column(String(200), default="")
    avg_confidence: Mapped[float | None] = mapped_column(Float)
    judge_score: Mapped[float | None] = mapped_column(Float)
    # Per-dimension judge scores (signal_grounding, hallucination_free, …)
    # shown in the approval card; judge_score is their weighted composite.
    judge_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    judge_feedback: Mapped[str] = mapped_column(Text, default="")
    # Composer's claim→signal mapping, rendered as evidence in review.
    grounding_notes: Mapped[str] = mapped_column(Text, default="")
    # How much the human changed the draft at approval: 0 = sent verbatim,
    # 1 = fully rewritten. None until (unless) a human reviews it. Fuels the
    # judge-calibration analytics and the fine-tuning export.
    edit_ratio: Mapped[float | None] = mapped_column(Float)
    touch_number: Mapped[int] = mapped_column(Integer, default=1)
    compose_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # pending_review | approved | rejected | sent | failed
    status: Mapped[str] = mapped_column(String(20), default="pending_review")
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str] = mapped_column(String(400), default="")
    sent_message_id: Mapped[str | None] = mapped_column(String(32))


class Message(Base, TimestampMixin):
    """Every inbound/outbound touch on any channel — the conversation timeline."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_ws_prospect", "workspace_id", "prospect_id"),
        # Kill-switch/analytics scan the rolling window every minute.
        Index("ix_messages_ws_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    prospect_id: Mapped[str | None] = mapped_column(ForeignKey("prospects.id"))
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # email|sms|voice
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # out|in
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    # delivered|opened|clicked|bounced|complained (email); classified intent (in)
    intent: Mapped[str | None] = mapped_column(String(20))  # warm|cold|neutral|question
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_uid", name="uq_booking_ws_uid"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    prospect_id: Mapped[str | None] = mapped_column(ForeignKey("prospects.id"))
    provider_uid: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    # confirmed | cancelled | rescheduled
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


# ── compliance & reliability ──────────────────────────────────────────


class Suppression(Base):
    """Durable do-not-contact list. Checked before every outbound send."""

    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "channel", "address", name="uq_suppression"
        ),
        # Kill-switch counts opt-outs over a rolling window every minute.
        Index("ix_suppressions_ws_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # email|sms
    address: Mapped[str] = mapped_column(String(320), nullable=False)  # email or E.164
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    # opt_out | bounce | complaint | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookEvent(Base):
    """Idempotency ledger: one row per (provider, external id); replays no-op."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_webhook_provider_ext"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base, TimestampMixin):
    """DB-backed job queue. Claimed with SKIP LOCKED on Postgres."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_run_after", "status", "run_after"),
        UniqueConstraint("idempotency_key", name="uq_jobs_idem"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    # MutableDict: in-place payload mutations are dirty-tracked and persisted.
    payload: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | running | done | failed (will retry) | dead
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(200))


class DailyCounter(Base):
    """Per-workspace daily counters enforcing volume caps.

    `channel` is either a send channel ("email"/"sms") or a campaign queue
    bucket ("q:<campaign id>") used to make campaign daily_cap actually
    daily."""

    __tablename__ = "daily_counters"
    __table_args__ = (
        UniqueConstraint("workspace_id", "date", "channel", name="uq_counter"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)


class RateLimitCounter(Base):
    """Fixed-window rate-limit counters, shared across every instance.

    The limiter used to live in process memory, which meant N web instances
    granted N times the configured allowance and a restart cleared every
    lockout. This table makes the count global without adding Redis — the
    endpoints it guards (login, setup, unsubscribe) are low-volume, so one
    upsert per request is cheap.

    `window_start` is the epoch second at which the current fixed window
    began, so (bucket, window_start) is the counter's identity and old rows
    are trivially purgeable by age.
    """

    __tablename__ = "rate_limit_counters"
    __table_args__ = (
        UniqueConstraint("bucket", "window_start", name="uq_rate_window"),
        Index("ix_rate_limit_window_start", "window_start"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # "<limiter name>:<client key>", e.g. "login-ip:203.0.113.4"
    bucket: Mapped[str] = mapped_column(String(320), nullable=False)
    window_start: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

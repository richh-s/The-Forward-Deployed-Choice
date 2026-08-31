"""Tenacious Conversion Engine — multi-tenant outbound conversion product.

Package layout:
    config.py        — environment-driven settings; fails fast on unsafe
                       production config (pydantic-settings)
    db.py            — async SQLAlchemy engine/session, URL normalization,
                       pool tuning
    models.py        — ORM models (all tenant data scoped by workspace_id)
    security.py      — password hashing (off-loop), session/CSRF tokens,
                       HKDF-derived credential encryption with rotation
    csrf.py          — CSRF dependency (session HMAC + double-submit cookie)
    ratelimit.py     — DB-backed fixed-window limiters, shared across
                       instances (login, public)
    middleware.py    — security headers, request IDs, body-size limits
    observability.py — JSON logging, request correlation, optional Sentry
    queue.py         — Postgres-backed job queue + worker loop (SAVEPOINT
                       enqueue, reaper, retention, graceful cancel)
    services/        — LLM composition, judge gate, reply agent, channels,
                       CRM, booking, suppression, sequences, kill-switch
    webhooks/        — inbound webhook signature verification
    routes/          — dashboard, API, jobs view, and webhook endpoints
    app.py           — application factory (health, metrics, lifecycles)
"""

__version__ = "1.0.0"

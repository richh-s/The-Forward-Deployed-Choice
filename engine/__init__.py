"""Tenacious Conversion Engine — multi-tenant outbound conversion product.

Package layout:
    config.py    — environment-driven settings (pydantic-settings)
    db.py        — async SQLAlchemy engine/session
    models.py    — ORM models (all tenant data scoped by workspace_id)
    security.py  — password hashing, session tokens, credential encryption
    queue.py     — Postgres-backed job queue + worker loop
    services/    — LLM composition, judge gate, reply agent, channels, CRM,
                   booking, suppression, sequences, kill-switch
    webhooks/    — inbound webhook signature verification
    routes/      — dashboard, API, and webhook endpoints
    app.py       — application factory
"""

__version__ = "1.0.0"

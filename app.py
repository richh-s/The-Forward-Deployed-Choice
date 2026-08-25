"""Backward-compatible entry point.

The original single-file webhook server that lived here has been replaced by
the production application in the engine/ package (multi-tenant, database-
backed, signature-verified webhooks, job queue, dashboard). `uvicorn app:app`
and `uvicorn server:app` are equivalent.
"""
from engine.app import create_app

app = create_app()

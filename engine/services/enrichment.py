"""Prospect signal enrichment via a per-workspace HTTP source.

`Prospect.signals` is the contract the composer consumes: a JSON object of
named signals, each ideally carrying a `confidence` (high/medium/low). This
service fills it from a workspace-configured enrichment endpoint (Settings →
credentials → enrichment): any HTTPS service that accepts a POSTed prospect
and returns a signals object — a Clay/Apollo-style wrapper, an internal
service, or the research `enrichment/` pipeline exposed behind FastAPI.

Contract:
    POST <url>          (Authorization: Bearer <api_key> when configured)
    body: {"email", "name", "company", "title", "phone"}
    200 → {"signals": {...}}  or a bare signals object {...}

Failure policy: transport/5xx errors retry via the job queue; on the final
attempt the prospect proceeds UNENRICHED (stage 'enriched', empty signals —
composing in inquiry mode) rather than stalling in the pipeline forever.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Prospect, Workspace
from engine.services.credentials import get_credentials
from engine.services.http import get_client

logger = logging.getLogger(__name__)


async def enrichment_configured(db: AsyncSession, workspace_id: str) -> bool:
    creds = await get_credentials(db, workspace_id, "enrichment")
    return bool(creds and creds.get("url"))


async def fetch_signals(
    db: AsyncSession, workspace: Workspace, prospect: Prospect
) -> dict:
    """Call the workspace's enrichment endpoint for one prospect.
    Raises on transport/HTTP errors (the job queue handles retries)."""
    creds = await get_credentials(db, workspace.id, "enrichment")
    if not creds or not creds.get("url"):
        return {}
    headers = {}
    if creds.get("api_key"):
        headers["Authorization"] = f"Bearer {creds['api_key']}"
    resp = await get_client().post(
        creds["url"],
        headers=headers,
        json={
            "email": prospect.email,
            "name": prospect.name,
            "company": prospect.company,
            "title": prospect.title,
            "phone": prospect.phone or "",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    signals = body.get("signals", body) if isinstance(body, dict) else None
    if not isinstance(signals, dict):
        raise ValueError(
            f"Enrichment endpoint returned no signals object: {str(body)[:200]}"
        )
    return signals


async def enrich_prospect(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    final_attempt: bool,
) -> None:
    """Populate prospect.signals and advance to 'enriched'."""
    try:
        signals = await fetch_signals(db, workspace, prospect)
    except (httpx.HTTPError, ValueError):
        if not final_attempt:
            raise
        # Out of retries: don't hold the prospect hostage to a broken
        # enrichment source — compose without signals (inquiry mode).
        logger.warning(
            "Enrichment failed for prospect %s after retries; "
            "proceeding unenriched", prospect.id,
        )
        signals = {}
    if signals:
        prospect.signals = signals
    if prospect.stage == "new":
        prospect.stage = "enriched"

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
    200 → {"signals": {...}, "icp_segment": 1-4 (optional)}
          or a bare signals object {...}

The challenge pipeline is served in exactly this shape by
`uvicorn enrichment.service:app` — see enrichment/service.py.

Failure policy: transport/5xx errors retry via the job queue; on the final
attempt the prospect proceeds UNENRICHED (stage 'enriched', empty signals —
composing in inquiry mode) rather than stalling in the pipeline forever.
"""
import logging

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
    """Call the workspace's enrichment endpoint for one prospect. Returns the
    response body (a dict with "signals" and optionally "icp_segment", or a
    bare signals object). Raises on transport/HTTP errors (the job queue
    handles retries)."""
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
    # Everything in `signals` lands verbatim in LLM prompts (billed by the
    # token) and in the DB — cap the response size before parsing.
    if len(resp.content) > 262_144:
        raise ValueError(
            f"Enrichment response too large ({len(resp.content)} bytes; "
            "max 256 KB)"
        )
    body = resp.json()
    if not isinstance(body, dict):
        raise ValueError(
            f"Enrichment endpoint returned no signals object: {str(body)[:200]}"
        )
    return body


async def enrich_prospect(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    final_attempt: bool,
) -> None:
    """Populate prospect.signals (and ICP segment) and advance to 'enriched'."""
    try:
        body = await fetch_signals(db, workspace, prospect)
    except Exception:  # noqa: BLE001 — see below
        if not final_attempt:
            raise
        # Out of retries: don't hold the prospect hostage to a broken
        # enrichment source — compose without signals (inquiry mode).
        # Deliberately broad: ANY terminal enrichment failure (transport,
        # bad response, credential decrypt error) must degrade to inquiry
        # mode rather than dead-letter — a dead job here would strand the
        # prospect at 'new' behind the enrich:{id} idempotency key.
        logger.warning(
            "Enrichment failed for prospect %s after retries; "
            "proceeding unenriched", prospect.id, exc_info=True,
        )
        body = {}
        # Leave a visible trace for the operator (shown on the prospect
        # page); the composer ignores non-dict signal values.
        prospect.signals = {"_enrichment_failed": True}
    signals = body.get("signals", body)
    if isinstance(signals, dict) and signals:
        # A source that declares its output synthetic (proxy-derived, not
        # live lookups — e.g. the bundled challenge pipeline) is marked on
        # the prospect so the composer can never promote its signals to
        # assertion mode.
        if body.get("synthetic"):
            signals = {**signals, "_synthetic": True}
        prospect.signals = signals
    segment = body.get("icp_segment")
    if isinstance(segment, int) and 1 <= segment <= 4:
        prospect.icp_segment = segment
    if prospect.stage == "new":
        prospect.stage = "enriched"

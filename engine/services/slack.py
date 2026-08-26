"""Slack notifications via a per-workspace incoming webhook.

Configured in Settings → credentials → slack ({"webhook_url": ...}). Used to
push operational moments to where operators already live: drafts awaiting
review, escalations, kill-switch pauses, and the weekly digest. Strictly
best-effort — a Slack outage must never fail a pipeline job, so every error
is swallowed and logged.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from engine.services.credentials import get_credentials
from engine.services.http import get_client

logger = logging.getLogger(__name__)


async def notify(db: AsyncSession, workspace_id: str, text: str) -> bool:
    """Post a message to the workspace's Slack webhook, if configured.
    Returns True only when Slack accepted the message."""
    try:
        creds = await get_credentials(db, workspace_id, "slack")
        url = (creds or {}).get("webhook_url")
        if not url:
            return False
        resp = await get_client().post(url, json={"text": text})
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — notifications never break jobs
        logger.warning(
            "Slack notification failed for workspace %s: %s", workspace_id, exc
        )
        return False

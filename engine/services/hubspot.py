"""HubSpot CRM sync — create/update contacts and log the booking.

Failures raise (the job queue retries); nothing here fabricates contact IDs.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from engine.models import Prospect, Workspace
from engine.services.credentials import get_credentials
from engine.services.http import get_client

logger = logging.getLogger(__name__)

HUBSPOT_API = "https://api.hubapi.com"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=20),
    reraise=True,
)
async def _request(token: str, method: str, path: str, json_body: dict) -> httpx.Response:
    resp = await get_client().request(
        method,
        f"{HUBSPOT_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
    )
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()
    return resp


def _contact_properties(prospect: Prospect) -> dict:
    parts = (prospect.name or "").split()
    return {
        "email": prospect.email,
        "firstname": parts[0] if parts else "",
        "lastname": " ".join(parts[1:]) if len(parts) > 1 else "",
        "company": prospect.company or "",
        "jobtitle": prospect.title or "",
        "lifecyclestage": "lead",
    }


async def sync_contact(
    db: AsyncSession, workspace: Workspace, prospect: Prospect
) -> str | None:
    """Create (or find) the HubSpot contact for a prospect. Returns the real
    contact id, or None when HubSpot isn't configured for the workspace."""
    creds = await get_credentials(db, workspace.id, "hubspot")
    token = (creds or {}).get("access_token")
    if not token:
        return None

    resp = await _request(
        token,
        "POST",
        "/crm/v3/objects/contacts",
        {"properties": _contact_properties(prospect)},
    )
    if resp.status_code == 409:
        # Contact exists — the conflict message carries "Existing ID: <id>"
        detail = resp.json().get("message", "")
        contact_id = detail.rsplit("Existing ID: ", 1)[-1].strip() if "Existing ID:" in detail else None
        if not contact_id:
            # Fall back to a search by email.
            search = await _request(
                token,
                "POST",
                "/crm/v3/objects/contacts/search",
                {
                    "filterGroups": [{
                        "filters": [{
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": prospect.email,
                        }]
                    }]
                },
            )
            results = search.json().get("results", [])
            contact_id = results[0]["id"] if results else None
        if not contact_id:
            raise RuntimeError(
                f"HubSpot contact conflict for {prospect.email} but no id resolvable"
            )
    else:
        contact_id = resp.json().get("id")
        if not contact_id:
            raise RuntimeError(f"HubSpot create returned no id: {resp.text[:200]}")

    prospect.hubspot_contact_id = str(contact_id)
    await db.flush()
    return str(contact_id)


async def mark_meeting_booked(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    booking_time: str,
    booking_uid: str,
) -> None:
    creds = await get_credentials(db, workspace.id, "hubspot")
    token = (creds or {}).get("access_token")
    if not token:
        return
    contact_id = prospect.hubspot_contact_id
    if not contact_id:
        contact_id = await sync_contact(db, workspace, prospect)
        if not contact_id:
            return
    resp = await _request(
        token,
        "PATCH",
        f"/crm/v3/objects/contacts/{contact_id}",
        {
            "properties": {
                "lifecyclestage": "opportunity",
                "hs_lead_status": "CONNECTED",
                "meeting_booked": "true",
                "meeting_time": booking_time,
                "cal_booking_id": booking_uid,
            }
        },
    )
    resp.raise_for_status()
    logger.info("HubSpot contact %s marked booked (%s)", contact_id, booking_uid)

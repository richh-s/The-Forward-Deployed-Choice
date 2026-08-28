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

from engine.models import Message, Prospect, Workspace, as_aware, utcnow
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
    # 400 is returned (not raised) so sync_contact can detect a portal
    # missing the custom properties and degrade to standard fields — raising
    # here made that fallback unreachable and dead-lettered every sync.
    if resp.status_code not in (200, 201, 400, 409):
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


def _enrichment_properties(prospect: Prospect) -> dict:
    """Tenacious custom properties (scripts/setup_hubspot_properties.py
    creates them in the portal). Challenge requirement: every lead object in
    HubSpot references its Crunchbase record and carries the enrichment
    provenance."""
    signals = prospect.signals or {}
    funding = signals.get("signal_1_funding_event") or {}
    maturity = signals.get("signal_5_ai_maturity") or {}
    props: dict = {"signal_source": "conversion-engine"}
    if funding.get("crunchbase_id"):
        props["crunchbase_id"] = str(funding["crunchbase_id"])
    if funding.get("amount_usd"):
        props["funding_amount_usd"] = str(funding["amount_usd"])
    if prospect.icp_segment:
        props["icp_segment"] = str(prospect.icp_segment)
    if maturity.get("score") is not None:
        props["ai_maturity_score"] = str(maturity["score"])
    if maturity.get("confidence"):
        props["signal_confidence"] = str(maturity["confidence"])
    if signals:
        props["enrichment_timestamp"] = utcnow().isoformat()
    return props


async def sync_contact(
    db: AsyncSession, workspace: Workspace, prospect: Prospect
) -> str | None:
    """Create (or find) the HubSpot contact for a prospect. Returns the real
    contact id, or None when HubSpot isn't configured for the workspace."""
    creds = await get_credentials(db, workspace.id, "hubspot")
    token = (creds or {}).get("access_token")
    if not token:
        return None

    # Synthetic demo addresses live on reserved TLDs precisely so they can
    # never deliver — HubSpot (correctly) rejects them as invalid emails.
    # Skip quietly rather than dead-lettering a job that can never succeed.
    if prospect.email.rsplit(".", 1)[-1].lower() in (
        "example", "invalid", "test", "localhost",
    ):
        logger.info(
            "Skipping HubSpot sync for %s: reserved-TLD demo address",
            prospect.email,
        )
        return None

    properties = {**_contact_properties(prospect), **_enrichment_properties(prospect)}
    resp = await _request(
        token, "POST", "/crm/v3/objects/contacts", {"properties": properties}
    )
    if resp.status_code == 400 and "PROPERTY" in resp.text.upper():
        # Portal without the Tenacious custom properties (setup script not
        # run yet) — degrade to the standard fields rather than losing the
        # contact.
        logger.warning(
            "HubSpot portal lacks custom enrichment properties; syncing "
            "standard fields only (run scripts/setup_hubspot_properties.py)"
        )
        resp = await _request(
            token, "POST", "/crm/v3/objects/contacts",
            {"properties": _contact_properties(prospect)},
        )
    if resp.status_code == 400:
        # Any remaining 400 is deterministic (bad email, malformed value) —
        # retrying re-sends the identical request.
        from engine.queue import PermanentJobError

        raise PermanentJobError(
            f"HubSpot rejected the contact for {prospect.email}: "
            f"{resp.text[:300]}"
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


# HubSpot v3 association type: note → contact.
_NOTE_TO_CONTACT = 202


async def log_conversation_event(
    db: AsyncSession, workspace: Workspace, prospect: Prospect, message: Message
) -> None:
    """Log one conversation event (any channel, either direction) as a Note
    on the contact's HubSpot timeline — the challenge requires every
    conversation event in the CRM, not just contact creation and booking."""
    creds = await get_credentials(db, workspace.id, "hubspot")
    token = (creds or {}).get("access_token")
    if not token:
        return
    contact_id = prospect.hubspot_contact_id or await sync_contact(
        db, workspace, prospect
    )
    if not contact_id:
        return
    direction = "→ outbound" if message.direction == "out" else "← inbound"
    body_lines = [
        f"[{message.channel}] {direction}",
        f"Subject: {message.subject}" if message.subject else "",
        (message.body or "")[:4000],
    ]
    ts = as_aware(message.created_at) or utcnow()
    resp = await _request(
        token,
        "POST",
        "/crm/v3/objects/notes",
        {
            "properties": {
                "hs_note_body": "\n".join(line for line in body_lines if line),
                "hs_timestamp": str(int(ts.timestamp() * 1000)),
            },
            "associations": [{
                "to": {"id": contact_id},
                "types": [{
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": _NOTE_TO_CONTACT,
                }],
            }],
        },
    )
    if resp.status_code == 400:
        from engine.queue import PermanentJobError

        raise PermanentJobError(
            f"HubSpot rejected the note for contact {contact_id}: "
            f"{resp.text[:300]}"
        )
    resp.raise_for_status()
    logger.info(
        "HubSpot note logged | contact=%s message=%s", contact_id, message.id
    )


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
    full_props = {
        "lifecyclestage": "opportunity",
        "hs_lead_status": "CONNECTED",
        "meeting_booked": "true",
        "meeting_time": booking_time,
        "cal_booking_id": booking_uid,
    }
    resp = await _request(
        token,
        "PATCH",
        f"/crm/v3/objects/contacts/{contact_id}",
        {"properties": full_props},
    )
    if resp.status_code == 400 and "PROPERTY" in resp.text.upper():
        # Same degrade path as sync_contact: keep the lifecycle change even
        # on a portal without the custom booking properties.
        logger.warning(
            "HubSpot portal lacks custom booking properties; marking "
            "lifecycle only (run scripts/setup_hubspot_properties.py)"
        )
        resp = await _request(
            token,
            "PATCH",
            f"/crm/v3/objects/contacts/{contact_id}",
            {"properties": {
                "lifecyclestage": "opportunity",
                "hs_lead_status": "CONNECTED",
            }},
        )
    resp.raise_for_status()
    logger.info("HubSpot contact %s marked booked (%s)", contact_id, booking_uid)

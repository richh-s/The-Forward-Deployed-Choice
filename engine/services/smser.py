"""Outbound SMS via Africa's Talking (HTTP API, async, with retries).

The africastalking SDK is synchronous and initializes globally, which fights
both asyncio and multi-tenancy — so we call the REST API directly.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from engine.config import get_settings
from engine.models import Message, Prospect, Workspace
from engine.services.credentials import get_credentials
from engine.services.suppression import SendBlocked, check_can_send, normalize_phone

logger = logging.getLogger(__name__)

AT_LIVE_URL = "https://api.africastalking.com/version1/messaging"
AT_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=20),
    reraise=True,
)
async def _at_send(
    username: str, api_key: str, to: str, body: str, sender_id: str | None
) -> dict:
    url = AT_SANDBOX_URL if username == "sandbox" else AT_LIVE_URL
    data = {"username": username, "to": to, "message": body}
    if sender_id:
        data["from"] = sender_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            url,
            headers={"apiKey": api_key, "Accept": "application/json"},
            data=data,
        )
        resp.raise_for_status()
        return resp.json()


async def send_sms(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect | None,
    *,
    to_phone: str,
    body: str,
    skip_policy_checks: bool = False,
) -> Message:
    """Policy-checked, sink-gated SMS send.

    skip_policy_checks=True is ONLY for compliance confirmations (STOP/HELP
    acknowledgements), which must go out even to suppressed numbers.
    """
    settings = get_settings()
    creds = await get_credentials(db, workspace.id, "africastalking")
    if not creds or not creds.get("api_key"):
        raise SendBlocked(
            "Africa's Talking credentials are not configured for this workspace"
        )

    to_phone = normalize_phone(to_phone)
    if not skip_policy_checks:
        await check_can_send(db, workspace, "sms", to_phone, prospect)

    if not settings.live_mode:
        if not settings.sink_phone:
            raise SendBlocked(
                "LIVE_MODE is off and no SINK_PHONE is configured — refusing to send"
            )
        body = f"[SINK — intended for {to_phone}] {body}"
        to_phone = normalize_phone(settings.sink_phone)

    result = await _at_send(
        creds.get("username", "sandbox"),
        creds["api_key"],
        to_phone,
        body,
        workspace.sms_sender_id,
    )
    recipients = (result.get("SMSMessageData") or {}).get("Recipients") or []
    provider_id = recipients[0].get("messageId") if recipients else None
    status = recipients[0].get("status", "unknown") if recipients else "unknown"
    if status not in ("Success", "Sent"):
        raise RuntimeError(f"Africa's Talking rejected the SMS: {result}")

    message = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id if prospect else None,
        channel="sms",
        direction="out",
        body=body,
        provider_message_id=provider_id,
        status="sent",
        meta={"sink_mode": not settings.live_mode},
    )
    db.add(message)
    await db.flush()
    logger.info(
        "SMS sent | ws=%s prospect=%s live=%s",
        workspace.id, prospect.id if prospect else "-", settings.live_mode,
    )
    return message

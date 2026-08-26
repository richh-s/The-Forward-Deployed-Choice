"""Outbound WhatsApp via the Twilio Messages API.

Scope: WhatsApp is a *conversation* channel — the reply agent answers
inbound WhatsApp messages inside Meta's 24-hour customer-service window.
Cold outbound over WhatsApp requires pre-approved template messages and is
deliberately not implemented; campaign touches stay on email.

Reuses the channel-generic rails: suppression list (channel "whatsapp"),
per-workspace daily cap, sink mode, and the Message timeline.
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

from engine.config import get_settings
from engine.models import Message, Prospect, Workspace
from engine.services.credentials import get_credentials
from engine.services.http import get_client
from engine.services.suppression import (
    SendBlocked,
    check_can_send,
    is_suppressed,
    normalize_phone,
)

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


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
async def _twilio_send(
    account_sid: str, auth_token: str, from_number: str, to: str, body: str
) -> dict:
    resp = await get_client().post(
        TWILIO_API.format(sid=account_sid),
        auth=(account_sid, auth_token),
        data={
            "From": f"whatsapp:{from_number}",
            "To": f"whatsapp:{to}",
            "Body": body,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def send_whatsapp(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect | None,
    *,
    to_phone: str,
    body: str,
    skip_policy_checks: bool = False,
) -> Message:
    """Policy-checked, sink-gated WhatsApp send (mirrors send_sms).

    skip_policy_checks=True is ONLY for compliance confirmations (STOP/HELP
    acknowledgements), which must go out even to suppressed numbers."""
    settings = get_settings()
    creds = await get_credentials(db, workspace.id, "twilio")
    if not creds or not creds.get("account_sid") or not creds.get("auth_token"):
        raise SendBlocked("Twilio credentials are not configured for this workspace")
    if not creds.get("from_number"):
        raise SendBlocked("Twilio from_number is not configured for this workspace")

    to_phone = normalize_phone(to_phone)
    intended_recipient = to_phone
    if not skip_policy_checks:
        await check_can_send(db, workspace, "whatsapp", to_phone, prospect)

    if not settings.live_mode:
        if not settings.sink_phone:
            raise SendBlocked(
                "LIVE_MODE is off and no SINK_PHONE is configured — refusing to send"
            )
        body = f"[SINK — intended for {to_phone}] {body}"
        to_phone = normalize_phone(settings.sink_phone)

    # Last-instant re-check (STOP handled while this send was in flight).
    if not skip_policy_checks and await is_suppressed(
        db, workspace.id, "whatsapp", intended_recipient
    ):
        raise SendBlocked("Recipient is on the whatsapp suppression list")

    result = await _twilio_send(
        creds["account_sid"], creds["auth_token"], creds["from_number"],
        to_phone, body,
    )
    message = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id if prospect else None,
        channel="whatsapp",
        direction="out",
        body=body,
        provider_message_id=result.get("sid"),
        status="sent",
        meta={"sink_mode": not settings.live_mode},
    )
    db.add(message)
    await db.flush()
    logger.info(
        "WhatsApp sent | ws=%s prospect=%s live=%s",
        workspace.id, prospect.id if prospect else "-", settings.live_mode,
    )
    return message

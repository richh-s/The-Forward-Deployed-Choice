"""Outbound SMS via Africa's Talking, with Twilio as the fallback carrier.

Provider selection per workspace: Africa's Talking when its credential has
an api_key (the product's primary SMS carrier — best delivery on African
networks); otherwise Twilio's Messages API when that credential has a
from_number. The africastalking SDK is synchronous and initializes
globally, which fights both asyncio and multi-tenancy — so we call the
REST APIs directly.
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
from engine.queue import PermanentJobError
from engine.services.credentials import get_credentials
from engine.services.http import get_client
from engine.services.suppression import (
    SendBlocked,
    check_can_send,
    is_suppressed,
    normalize_phone,
)

logger = logging.getLogger(__name__)

AT_LIVE_URL = "https://api.africastalking.com/version1/messaging"
AT_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=20),
    reraise=True,
)
async def _twilio_sms_send(
    account_sid: str, auth_token: str, from_number: str, to: str, body: str
) -> dict:
    resp = await get_client().post(
        TWILIO_API.format(sid=account_sid),
        auth=(account_sid, auth_token),
        data={"From": from_number, "To": to, "Body": body},
    )
    if resp.status_code == 400:
        # Deterministic recipient rejection (unverified trial number,
        # invalid destination) — do not re-bill retries.
        raise PermanentJobError(f"Twilio rejected the SMS: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=20),
    reraise=True,
)
async def _at_send(
    username: str, api_key: str, to: str, body: str, sender_id: str | None
) -> dict:
    url = AT_SANDBOX_URL if username == "sandbox" else AT_LIVE_URL
    data = {"username": username, "to": to, "message": body}
    if sender_id:
        data["from"] = sender_id
    resp = await get_client().post(
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
    is_reply: bool = False,
) -> Message:
    """Policy-checked, sink-gated SMS send.

    skip_policy_checks=True is ONLY for compliance confirmations (STOP/HELP
    acknowledgements), which must go out even to suppressed numbers.
    """
    settings = get_settings()
    creds = await get_credentials(db, workspace.id, "africastalking")
    twilio_creds = None
    if not creds or not creds.get("api_key"):
        twilio_creds = await get_credentials(db, workspace.id, "twilio")
        if not (
            twilio_creds
            and twilio_creds.get("account_sid")
            and twilio_creds.get("auth_token")
            and twilio_creds.get("from_number")
        ):
            raise SendBlocked(
                "No SMS carrier configured: add Africa's Talking credentials "
                "(api_key) or Twilio credentials (account_sid, auth_token, "
                "from_number) for this workspace"
            )

    to_phone = normalize_phone(to_phone)
    intended_recipient = to_phone
    if not skip_policy_checks:
        await check_can_send(
            db, workspace, "sms", to_phone, prospect, is_reply=is_reply
        )

    if not settings.live_mode:
        if not settings.sink_phone:
            raise SendBlocked(
                "LIVE_MODE is off and no SINK_PHONE is configured — refusing to send"
            )
        body = f"[SINK — intended for {to_phone}] {body}"
        to_phone = normalize_phone(settings.sink_phone)

    # Last-instant re-check (STOP handled while this send was in flight).
    if not skip_policy_checks and await is_suppressed(
        db, workspace.id, "sms", intended_recipient
    ):
        raise SendBlocked("Recipient is on the sms suppression list")

    if twilio_creds is not None:
        result = await _twilio_sms_send(
            twilio_creds["account_sid"], twilio_creds["auth_token"],
            twilio_creds["from_number"], to_phone, body,
        )
        provider_id = result.get("sid")
        carrier = "twilio"
    else:
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
            # The API accepted the request but rejected this recipient
            # (invalid number, blacklist, no credit) — retrying re-bills the
            # same call for the same deterministic answer.
            raise PermanentJobError(f"Africa's Talking rejected the SMS: {result}")
        carrier = "africastalking"

    message = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id if prospect else None,
        channel="sms",
        direction="out",
        body=body,
        provider_message_id=provider_id,
        status="sent",
        meta={"sink_mode": not settings.live_mode, "carrier": carrier},
    )
    db.add(message)
    await db.flush()
    logger.info(
        "SMS sent | ws=%s prospect=%s live=%s",
        workspace.id, prospect.id if prospect else "-", settings.live_mode,
    )
    return message

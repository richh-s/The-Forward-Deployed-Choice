"""Telegram bot channel — free, carrier-less, and first-class in markets
where Telegram is the default messenger.

Two roles, one bot (Settings → credentials → telegram):

- Operator notifications: everything Slack gets (drafts awaiting review,
  escalations, kill-switch) also lands in `operator_chat_id`. Best-effort,
  never fails a job.
- Conversational prospect channel: a prospect who opens the bot via their
  personal deep link (t.me/<bot>?start=<prospect_id>) is linked to their
  prospect row; from then on the reply agent answers them on Telegram
  behind the same draft-approval gate, suppression list (channel
  "telegram", address = chat id), caps, and sink mode as every other
  channel. /stop opts them out everywhere.

Sink mode: prospect-bound messages are rerouted to the operator chat with
the intended chat id noted — mirroring SINK_EMAIL/SINK_PHONE. No operator
chat configured → the send is refused, never silently delivered.
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
from engine.services.suppression import SendBlocked, check_can_send, is_suppressed

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


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
async def _tg_call(token: str, method: str, payload: dict) -> dict:
    resp = await get_client().post(
        TELEGRAM_API.format(token=token, method=method), json=payload
    )
    if resp.status_code == 400 or resp.status_code == 403:
        # Deterministic: bad chat id, bot blocked by the user, malformed
        # payload — retrying re-sends the identical request.
        raise PermanentJobError(
            f"Telegram rejected {method}: {resp.text[:300]}"
        )
    resp.raise_for_status()
    return resp.json()


async def notify_operator(db: AsyncSession, workspace_id: str, text: str) -> bool:
    """Best-effort operator ping (like slack.notify). True when delivered."""
    try:
        creds = await get_credentials(db, workspace_id, "telegram")
        token = (creds or {}).get("bot_token")
        chat_id = (creds or {}).get("operator_chat_id")
        if not token or not chat_id:
            return False
        await _tg_call(token, "sendMessage", {"chat_id": chat_id, "text": text})
        return True
    except Exception as exc:  # noqa: BLE001 — notifications never break jobs
        logger.warning(
            "Telegram notification failed for workspace %s: %s",
            workspace_id, exc,
        )
        return False


def deep_link(creds: dict, prospect: Prospect) -> str | None:
    """Personal bot link that binds the prospect to their chat on /start."""
    username = (creds or {}).get("bot_username", "").lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}?start={prospect.id}"


async def send_telegram(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    body: str,
    skip_policy_checks: bool = False,
    is_reply: bool = False,
) -> Message:
    """Policy-checked, sink-gated Telegram send to a linked prospect chat."""
    settings = get_settings()
    creds = await get_credentials(db, workspace.id, "telegram")
    if not creds or not creds.get("bot_token"):
        raise SendBlocked("Telegram bot is not configured for this workspace")
    chat_id = prospect.telegram_chat_id
    if not chat_id:
        raise SendBlocked(
            "Prospect has no linked Telegram chat (they must open the bot "
            "via their deep link first)"
        )

    if not skip_policy_checks:
        await check_can_send(
            db, workspace, "telegram", chat_id, prospect, is_reply=is_reply
        )

    target = chat_id
    if not settings.live_mode:
        operator_chat = creds.get("operator_chat_id")
        if not operator_chat:
            raise SendBlocked(
                "LIVE_MODE is off and no telegram operator_chat_id is "
                "configured — refusing to send"
            )
        body = f"[SINK — intended for chat {chat_id}] {body}"
        target = operator_chat

    # Last-instant re-check (/stop handled while this send was in flight).
    if not skip_policy_checks and await is_suppressed(
        db, workspace.id, "telegram", chat_id
    ):
        raise SendBlocked("Recipient is on the telegram suppression list")

    result = await _tg_call(
        creds["bot_token"], "sendMessage", {"chat_id": target, "text": body}
    )
    message = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        channel="telegram",
        direction="out",
        body=body,
        provider_message_id=str(
            (result.get("result") or {}).get("message_id", "")
        ) or None,
        status="sent",
        meta={"sink_mode": not settings.live_mode},
    )
    db.add(message)
    await db.flush()
    logger.info(
        "Telegram sent | ws=%s prospect=%s live=%s",
        workspace.id, prospect.id, settings.live_mode,
    )
    return message

"""Outbound email via Resend.

Live-mode gating: unless LIVE_MODE=true, every email is rerouted to the
configured sink address (with the intended recipient noted in a header),
so development and demos can never contact real prospects.
"""
import html
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
from engine.services.suppression import SendBlocked, check_can_send, is_suppressed

logger = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _paragraphs_html(body_text: str) -> str:
    return "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
        for p in body_text.split("\n\n")
        if p.strip()
    )


def render_html(body_text: str, unsubscribe_url: str) -> str:
    """Plain-text body → minimal HTML with a mandatory unsubscribe footer."""
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'line-height:1.5;color:#222">{_paragraphs_html(body_text)}'
        '<p style="margin-top:24px;font-size:12px;color:#888">'
        f'If you\'d rather not hear from us, <a href="{html.escape(unsubscribe_url)}">'
        "unsubscribe here</a>.</p></div>"
    )


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=20),
    reraise=True,
)
async def _resend_send(
    api_key: str, payload: dict, idempotency_key: str | None = None
) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key:
        # Resend dedupes on this key, so a job retry after a DB failure
        # cannot deliver the same email twice.
        headers["Idempotency-Key"] = idempotency_key
    resp = await get_client().post(RESEND_API, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


async def send_internal_email(
    db: AsyncSession,
    workspace: Workspace,
    *,
    to_email: str,
    subject: str,
    body: str,
    footer: str = "Internal message from your Conversion Engine workspace.",
) -> None:
    """Staff-facing email (test sends, weekly digests).

    Deliberately bypasses sink mode, suppression, caps, and the Message
    timeline: this is workspace staff mail, not prospect outreach — it
    exercises the real Resend credentials and rendering end to end."""
    creds = await get_credentials(db, workspace.id, "resend")
    if not creds or not creds.get("api_key"):
        raise SendBlocked("Resend credentials are not configured for this workspace")
    if not workspace.from_email:
        raise SendBlocked("Workspace sending address (from_email) is not configured")
    payload = {
        "from": f"{workspace.from_name or workspace.name} <{workspace.from_email}>",
        "to": [to_email],
        "subject": subject,
        "text": f"{body}\n\n---\n{footer}",
        "html": (
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            f'line-height:1.5;color:#222">{_paragraphs_html(body)}'
            '<p style="margin-top:24px;font-size:12px;color:#888">'
            f'{footer}</p></div>'
        ),
    }
    await _resend_send(creds["api_key"], payload)
    logger.info("Internal email sent | ws=%s to staff address", workspace.id)


async def send_test_email(
    db: AsyncSession,
    workspace: Workspace,
    *,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    """Send a draft preview to a logged-in staff member's own address."""
    await send_internal_email(
        db, workspace,
        to_email=to_email,
        subject=f"[TEST] {subject}",
        body=body,
        footer="This is an internal test send — no prospect received this email.",
    )


async def send_email(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    subject: str,
    body: str,
    compose_cost_usd: float = 0.0,
    idempotency_key: str | None = None,
) -> Message:
    """Policy-checked, suppressed-aware, sink-gated email send.
    Raises SendBlocked (policy) or httpx errors (transport, after retries)."""
    settings = get_settings()
    creds = await get_credentials(db, workspace.id, "resend")
    if not creds or not creds.get("api_key"):
        raise SendBlocked("Resend credentials are not configured for this workspace")
    if not workspace.from_email:
        raise SendBlocked("Workspace sending address (from_email) is not configured")

    await check_can_send(db, workspace, "email", prospect.email, prospect)

    to_address = prospect.email
    headers = {}
    if not settings.live_mode:
        if not settings.sink_email:
            raise SendBlocked(
                "LIVE_MODE is off and no SINK_EMAIL is configured — refusing to send"
            )
        headers["X-Intended-Recipient"] = prospect.email
        to_address = settings.sink_email

    unsubscribe_url = (
        f"{settings.base_url}/u/{prospect.unsubscribe_token}"
    )
    payload = {
        "from": f"{workspace.from_name or workspace.name} <{workspace.from_email}>",
        "to": [to_address],
        "subject": subject,
        "text": f"{body}\n\nUnsubscribe: {unsubscribe_url}",
        "html": render_html(body, unsubscribe_url),
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            **headers,
        },
    }
    # Last-instant re-check: an unsubscribe committed between the policy
    # check above and this point must still win.
    if await is_suppressed(db, workspace.id, "email", prospect.email):
        raise SendBlocked("Recipient is on the email suppression list")

    result = await _resend_send(
        creds["api_key"], payload, idempotency_key=idempotency_key
    )
    provider_id = result.get("id")
    if not provider_id:
        raise RuntimeError(f"Resend returned no message id: {result}")

    message = Message(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        channel="email",
        direction="out",
        subject=subject,
        body=body,
        provider_message_id=provider_id,
        status="sent",
        cost_usd=compose_cost_usd,
        meta={"sink_mode": not settings.live_mode},
    )
    db.add(message)
    await db.flush()
    logger.info(
        "Email sent | ws=%s prospect=%s live=%s resend_id=%s",
        workspace.id, prospect.id, settings.live_mode, provider_id,
    )
    return message

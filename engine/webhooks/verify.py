"""Inbound webhook signature verification.

Policy: fail closed. If a workspace has not configured the signing secret for
a provider, that provider's webhook is rejected — never processed unsigned.
Africa's Talking does not sign requests, so its route is protected by a
per-workspace secret URL token instead.
"""
import base64
import hashlib
import hmac
import time

from fastapi import HTTPException

# Svix spec: reject webhooks whose timestamp is outside ±5 minutes, so a
# captured request can't be replayed forever (the WebhookEvent ledger only
# holds ids for the retention window).
SVIX_TOLERANCE_SECONDS = 300


def _forbid(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def verify_svix(
    secret: str | None,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    payload: bytes,
) -> None:
    """Resend webhooks are delivered by Svix."""
    if not secret:
        raise _forbid("Resend webhook secret not configured")
    if not all([svix_id, svix_timestamp, svix_signature]):
        raise _forbid("Missing Svix signature headers")
    try:
        ts = float(svix_timestamp)
    except ValueError as exc:
        raise _forbid("Malformed Svix timestamp") from exc
    if abs(time.time() - ts) > SVIX_TOLERANCE_SECONDS:
        raise _forbid("Svix timestamp outside tolerance")
    to_sign = f"{svix_id}.{svix_timestamp}.".encode() + payload
    try:
        raw_key = base64.b64decode(secret.removeprefix("whsec_"))
    except Exception as exc:
        raise _forbid("Malformed webhook secret") from exc
    expected = base64.b64encode(
        hmac.new(raw_key, to_sign, hashlib.sha256).digest()
    ).decode()
    candidates = [
        sig.split(",", 1)[1] if "," in sig else sig
        for sig in svix_signature.split(" ")
    ]
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise _forbid("Invalid Svix signature")


def verify_calcom(secret: str | None, signature: str | None, payload: bytes) -> None:
    if not secret:
        raise _forbid("Cal.com webhook secret not configured")
    if not signature:
        raise _forbid("Missing Cal.com signature header")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise _forbid("Invalid Cal.com signature")


def verify_twilio(
    auth_token: str | None,
    signature: str | None,
    url: str,
    form_params: dict[str, str],
) -> None:
    """Twilio: HMAC-SHA1 over the full URL + params sorted by key, base64."""
    if not auth_token:
        raise _forbid("Twilio auth token not configured")
    if not signature:
        raise _forbid("Missing X-Twilio-Signature header")
    data = url + "".join(k + v for k, v in sorted(form_params.items()))
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
    if not hmac.compare_digest(expected, signature):
        raise _forbid("Invalid Twilio signature")


def verify_url_token(expected_token: str | None, presented: str) -> None:
    """Shared-secret URL token for providers that do not sign (Africa's
    Talking). The token is part of the registered webhook URL."""
    if not expected_token:
        raise _forbid("Webhook token not configured for this workspace")
    if not hmac.compare_digest(expected_token, presented):
        raise _forbid("Invalid webhook token")

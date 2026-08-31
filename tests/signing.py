"""Request-signing helpers for webhook handler tests.

Each provider signs differently; these build the exact headers the real
provider would send so handler tests exercise the verified path rather than
bypassing it.
"""
import base64
import hashlib
import hmac
import json
import time

from engine.db import db_session
from engine.services.credentials import set_credentials

# Svix secrets are base64 of the raw HMAC key, prefixed whsec_.
RESEND_KEY = b"resend-test-key-32-bytes-long!!!"
RESEND_SECRET = "whsec_" + base64.b64encode(RESEND_KEY).decode()
CALCOM_SECRET = "calcom-test-secret"
TWILIO_TOKEN = "twilio-test-auth-token"
AT_TOKEN = "africastalking-url-token-32chars"
TELEGRAM_SECRET = "telegram-webhook-secret-value"


async def configure(workspace_id: str, provider: str, **overrides) -> None:
    """Store the signing credentials a provider's route requires."""
    defaults = {
        "resend": {"api_key": "re_test", "webhook_secret": RESEND_SECRET},
        "calcom": {"api_key": "cal_test", "webhook_secret": CALCOM_SECRET},
        "twilio": {
            "account_sid": "AC" + "0" * 32,
            "auth_token": TWILIO_TOKEN,
            "from_number": "+15550001111",
        },
        "africastalking": {
            "username": "sandbox", "api_key": "at_test",
            "webhook_token": AT_TOKEN,
        },
        "telegram": {
            "bot_token": "123:ABC", "bot_username": "acme_bot",
            "operator_chat_id": "999", "webhook_secret": TELEGRAM_SECRET,
        },
    }[provider] | overrides
    async with db_session() as db:
        await set_credentials(db, workspace_id, provider, defaults)


def svix_headers(payload: bytes, *, svix_id: str = "msg_1", ts: int | None = None):
    ts = int(time.time()) if ts is None else ts
    to_sign = f"{svix_id}.{ts}.".encode() + payload
    sig = base64.b64encode(
        hmac.new(RESEND_KEY, to_sign, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": svix_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v1,{sig}",
    }


def resend_event(event_type: str, data: dict, *, svix_id: str = "msg_1"):
    """(content, headers) for a signed Resend webhook."""
    payload = json.dumps({"type": event_type, "data": data}).encode()
    return payload, svix_headers(payload, svix_id=svix_id)


def calcom_event(trigger: str, payload: dict):
    body = json.dumps({"triggerEvent": trigger, "payload": payload}).encode()
    sig = hmac.new(CALCOM_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Cal-Signature-256": sig}


def twilio_headers(url: str, form: dict[str, str]) -> dict[str, str]:
    data = url + "".join(k + v for k, v in sorted(form.items()))
    sig = base64.b64encode(
        hmac.new(TWILIO_TOKEN.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    return {"X-Twilio-Signature": sig}


def telegram_headers() -> dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET}

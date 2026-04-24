"""
Twilio Voice — outbound discovery call initiator.

Flow:
  1. Call initiate_discovery_call() after a prospect replies and qualifies.
  2. Twilio dials the prospect; on pickup it fetches TwiML from /webhooks/voice.
  3. Prospect presses 1 to connect live or 2 to receive a calendar link by SMS.
  4. Final call status lands at /webhooks/voice/status.

Required env vars:
  TWILIO_ACCOUNT_SID   — from console.twilio.com
  TWILIO_AUTH_TOKEN    — from console.twilio.com
  TWILIO_FROM_NUMBER   — your Twilio phone number (+E.164)
  WEBHOOK_BASE_URL     — public URL of the webhook server (e.g. Render URL)
  TENACIOUS_SALES_PHONE — internal number Twilio bridges to when prospect presses 1
"""

import os
import logging

logger = logging.getLogger(__name__)


def initiate_discovery_call(
    to_number: str,
    prospect_name: str,
    company: str,
) -> dict:
    """
    Initiate an outbound Twilio Voice call to a qualified prospect.

    Returns the Twilio Call SID on success, or a mock result if credentials
    are not configured (safe for local demo without live Twilio account).
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    webhook_base = os.environ.get("WEBHOOK_BASE_URL", "http://localhost:8000")

    if not all([account_sid, auth_token, from_number]):
        logger.warning(
            "Twilio credentials not configured — returning mock call result. "
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to enable live calls."
        )
        return {
            "sid":    "CA_mock_demo_call",
            "status": "queued",
            "to":     to_number,
            "mock":   True,
        }

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)

        # Pass prospect context as query params so the TwiML webhook can
        # personalise the greeting without a database lookup.
        import urllib.parse
        params = urllib.parse.urlencode({
            "prospect_name": prospect_name,
            "company":       company,
        })
        twiml_url = f"{webhook_base}/webhooks/voice?{params}"
        status_url = f"{webhook_base}/webhooks/voice/status"

        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=twiml_url,
            status_callback=status_url,
            status_callback_method="POST",
        )
        logger.info(
            "Outbound call initiated: sid=%s to=%s prospect=%s",
            call.sid, to_number, prospect_name,
        )
        return {
            "sid":    call.sid,
            "status": call.status,
            "to":     to_number,
            "mock":   False,
        }
    except Exception as exc:
        logger.error("Twilio call failed: %s", exc)
        return {"sid": None, "status": "failed", "error": str(exc), "mock": False}

"""
Unified webhook server — deployed to Render free tier.
Stable public URL registered once across all four integrations:
  POST /webhooks/resend        — Resend email reply / bounce events
  POST /webhooks/sms           — Africa's Talking inbound SMS
  POST /webhooks/calcom        — Cal.com booking events
  POST /webhooks/hubspot       — HubSpot workflow triggers
  GET  /health                 — Render health check
"""
import os
import json
import hmac
import hashlib
import logging

import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

import africastalking

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

africastalking.initialize(
    username=os.environ.get("AT_USERNAME", "sandbox"),
    api_key=os.environ["AT_API_KEY"]
)
sms_service = africastalking.SMS

app = FastAPI(title="Tenacious Webhook Server")

# ── in-memory state (replace with Redis/DB for production) ──
OPT_OUT_COMMANDS = {"STOP", "UNSUB", "UNSUBSCRIBE", "QUIT", "CANCEL"}
opted_out: set = set()
conversation_state: dict = {}


# ─────────────────────────────────────────────
# Health check — Render pings this to confirm startup
# ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "tenacious-webhook-server"}


# ─────────────────────────────────────────────
# Resend — email reply / bounce / complaint events
# Docs: https://resend.com/docs/dashboard/webhooks/introduction
# ─────────────────────────────────────────────
@app.post("/webhooks/resend")
async def resend_webhook(
    request: Request,
    svix_id: str | None = Header(default=None),
    svix_timestamp: str | None = Header(default=None),
    svix_signature: str | None = Header(default=None),
):
    payload = await request.body()

    # Verify Svix signature if secret is configured
    webhook_secret = os.environ.get("RESEND_WEBHOOK_SECRET")
    if webhook_secret:
        _verify_svix(webhook_secret, svix_id, svix_timestamp, svix_signature, payload)

    event = json.loads(payload)
    event_type = event.get("type", "")
    data = event.get("data", {})

    logger.info("Resend event: %s | email_id: %s", event_type, data.get("email_id"))

    if event_type == "email.opened":
        _handle_email_opened(data)
    elif event_type == "email.clicked":
        _handle_email_clicked(data)
    elif event_type in ("email.bounced", "email.complained"):
        _handle_email_suppression(data, event_type)
    elif event_type == "email.received" or event_type == "inbound_email":
        _handle_email_reply(data)

    return {"received": True}


def _verify_svix(secret, svix_id, svix_timestamp, svix_signature, payload: bytes):
    if not all([svix_id, svix_timestamp, svix_signature]):
        raise HTTPException(status_code=400, detail="Missing Svix headers")
    to_sign = f"{svix_id}.{svix_timestamp}.{payload.decode()}"
    key = secret.removeprefix("whsec_")
    import base64
    raw_key = base64.b64decode(key)
    expected = base64.b64encode(
        hmac.new(raw_key, to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    if not any(
        hmac.compare_digest(f"v1,{expected}", sig)
        for sig in svix_signature.split(" ")
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _handle_email_opened(data: dict):
    logger.info("Email opened by %s", data.get("to", []))


def _handle_email_clicked(data: dict):
    logger.info("Email link clicked by %s", data.get("to", []))


def _handle_email_suppression(data: dict, event_type: str):
    for addr in data.get("to", []):
        logger.warning("Suppressing %s due to %s", addr, event_type)


def _handle_email_reply(data: dict):
    from_addr = data.get("from", "unknown")
    text = data.get("text", "")
    logger.info("Received inbound email reply from %s: %s", from_addr, text[:50])
    # Clear interface for downstream consumption
    _emit_downstream_reply_event({
        "channel": "email",
        "sender": from_addr,
        "content": text
    })


def _emit_downstream_reply_event(payload: dict):
    logger.info("Emitting downstream reply event: %s", payload)


# ─────────────────────────────────────────────
# Africa's Talking — inbound SMS
# Docs: https://developers.africastalking.com/docs/sms/receiving
# ─────────────────────────────────────────────
@app.post("/webhooks/sms")
async def sms_webhook(request: Request):
    data      = await request.form()
    message   = data.get("text", "").strip()
    phone     = data.get("from", "")
    shortcode = data.get("to", "")

    logger.info("SMS from %s: %s", phone, message)

    # TCPA compliance — opt-out handled immediately, no exceptions
    if message.upper() in OPT_OUT_COMMANDS:
        opted_out.add(phone)
        sms_service.send(
            "You have been unsubscribed. Reply START to resubscribe.",
            [phone],
            sender_id=shortcode
        )
        return {"status": "opted_out"}

    if phone in opted_out:
        return {"status": "suppressed"}

    if message.upper() == "START" and phone in opted_out:
        opted_out.discard(phone)
        sms_service.send(
            "You have been resubscribed. Reply STOP at any time to opt out.",
            [phone],
            sender_id=shortcode
        )
        return {"status": "resubscribed"}

    if message.upper() == "HELP":
        sms_service.send(
            "Reply STOP to unsubscribe. Contact hello@tenacious.dev for help.",
            [phone],
            sender_id=shortcode
        )
        return {"status": "help_sent"}

    state = conversation_state.get(phone, {})
    reply = _agent_sms_reply(phone, message, state)
    conversation_state[phone] = {
        "last_message": message,
        "last_reply":   reply,
        "turns":        state.get("turns", 0) + 1
    }

    # Emit downstream event before replying
    _emit_downstream_sms_event({
        "channel": "sms",
        "sender": phone,
        "content": message,
        "recipient": shortcode
    })

    sms_service.send(reply, [phone], sender_id=shortcode)
    return {"status": "replied"}


def _emit_downstream_sms_event(payload: dict):
    logger.info("Emitting downstream SMS event for routing: %s", payload)


def _agent_sms_reply(phone: str, message: str, state: dict) -> str:
    turns = state.get("turns", 0)
    if turns == 0:
        return (
            "Thanks for your reply! Happy to set up a quick 30-min call. "
            "What timezone works for you — US Eastern, Central, or Pacific?"
        )
    return (
        "Got it! I'll send a calendar link for that timezone shortly. "
        "Reply STOP at any time to opt out."
    )


# ─────────────────────────────────────────────
# Cal.com — booking lifecycle events
# Docs: https://cal.com/docs/core-features/webhooks
# ─────────────────────────────────────────────
@app.post("/webhooks/calcom")
async def calcom_webhook(
    request: Request,
    x_cal_signature_256: str | None = Header(default=None),
):
    payload = await request.body()

    secret = os.environ.get("CAL_WEBHOOK_SECRET")
    if secret and x_cal_signature_256:
        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_cal_signature_256):
            raise HTTPException(status_code=401, detail="Invalid Cal.com signature")

    event = json.loads(payload)
    trigger = event.get("triggerEvent", "")
    booking = event.get("payload", {})

    logger.info("Cal.com event: %s | booking uid: %s", trigger, booking.get("uid"))

    if trigger == "BOOKING_CREATED":
        await _on_booking_created(booking)
    elif trigger == "BOOKING_CANCELLED":
        await _on_booking_cancelled(booking)
    elif trigger == "BOOKING_RESCHEDULED":
        await _on_booking_rescheduled(booking)

    return {"received": True}


async def _on_booking_created(booking: dict):
    attendees = booking.get("attendees", [])
    logger.info(
        "Booking created: %s attendees, start=%s",
        len(attendees), booking.get("startTime")
    )
    # Update HubSpot contact if contact_id is in booking metadata
    metadata = booking.get("metadata", {})
    contact_id = metadata.get("hubspot_contact_id")
    if contact_id:
        await _update_hubspot_booking(
            contact_id,
            booking_time=booking.get("startTime", ""),
            cal_booking_id=str(booking.get("uid", ""))
        )


async def _on_booking_cancelled(booking: dict):
    logger.info("Booking cancelled: uid=%s", booking.get("uid"))


async def _on_booking_rescheduled(booking: dict):
    logger.info("Booking rescheduled: uid=%s", booking.get("uid"))


async def _update_hubspot_booking(
    contact_id: str, booking_time: str, cal_booking_id: str
):
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        return
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"properties": {
                "meeting_booked":   "true",
                "meeting_time":     booking_time,
                "cal_booking_id":   cal_booking_id
            }}
        )


# ─────────────────────────────────────────────
# HubSpot — workflow trigger / contact event
# Register in HubSpot as an outbound webhook action
# ─────────────────────────────────────────────
@app.post("/webhooks/hubspot")
async def hubspot_webhook(request: Request):
    events = await request.json()
    if not isinstance(events, list):
        events = [events]
    for ev in events:
        logger.info(
            "HubSpot event: %s | objectId: %s",
            ev.get("subscriptionType"),
            ev.get("objectId")
        )
    return {"received": len(events)}

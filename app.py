"""
Unified webhook server — deployed to Render free tier.
Stable public URL registered once across all integrations:
  POST /webhooks/resend        — Resend email reply / bounce events
  POST /webhooks/sms           — Africa's Talking inbound SMS
  POST /webhooks/calcom        — Cal.com booking events
  POST /webhooks/hubspot       — HubSpot workflow triggers
  POST /webhooks/voice         — Twilio Voice TwiML (inbound/outbound calls)
  POST /webhooks/voice/status  — Twilio call status callback
  POST /internal/register-prospect — Register prospect for email-to-SMS handoff
  GET  /health                 — Render health check
"""
import os
import re
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, Response
import imaplib
import email as email_lib
import threading
import time

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

# Prospect registry: email → {name, company, phone}
# Populated by /internal/register-prospect when outreach email is sent.
prospect_registry: dict = {}

WARM_KEYWORDS = re.compile(
    r"\b(interested|yes|sure|sounds good|tell me more|love to|would love|"
    r"happy to|let'?s|schedule|call|meet|talk|connect|demo|more info|"
    r"forward|absolutely|definitely|great idea|open to|keen)\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────
# Health check — Render pings this to confirm startup
# ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "tenacious-webhook-server"}


# ─────────────────────────────────────────────
# Internal — register prospect for email-to-SMS handoff
# Called by main.py immediately after outreach email is sent.
# ─────────────────────────────────────────────
@app.post("/internal/register-prospect")
async def register_prospect(request: Request):
    data = await request.json()
    email = (data.get("email") or "").lower().strip()
    if email:
        prospect_registry[email] = {
            "name":    data.get("name", ""),
            "company": data.get("company", ""),
            "phone":   data.get("phone", ""),
        }
        logger.info("Prospect registered for handoff: %s (%s)", email, data.get("company"))
    return {"registered": bool(email), "email": email}


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
    logger.info("Inbound email reply from %s: %s", from_addr, text[:80])
    _emit_downstream_reply_event({
        "channel": "email",
        "sender":  from_addr,
        "content": text,
    })


def _classify_reply_intent(text: str) -> str:
    """Classify email reply as warm / cold / neutral."""
    cold = re.search(
        r"\b(not interested|unsubscribe|remove me|no thanks|stop emailing)\b",
        text, re.IGNORECASE,
    )
    if cold:
        return "cold"
    if WARM_KEYWORDS.search(text):
        return "warm"
    return "neutral"


def _emit_downstream_reply_event(payload: dict):
    """
    Route warm email replies to SMS for scheduling handoff.
    Logs all events for Langfuse / audit trail.
    """
    sender = payload.get("sender", "")
    content = payload.get("content", "")
    intent = _classify_reply_intent(content)

    logger.info(
        "Downstream reply event | channel=email | sender=%s | intent=%s",
        sender, intent,
    )

    if intent != "warm":
        return

    # Look up prospect phone from registry; fall back to DEMO_PHONE env var
    prospect = prospect_registry.get(sender.lower(), {})
    phone = prospect.get("phone") or os.environ.get("DEMO_PHONE", "")

    if not phone:
        logger.warning("Warm reply from %s — no phone on file, skipping SMS handoff", sender)
        return

    name = (prospect.get("name") or "there").split()[0]
    company = prospect.get("company") or "your team"
    sms_body = (
        f"Hi {name} — thanks for your reply about {company}. "
        "Happy to set up a quick 30-min intro call. "
        "What timezone works — EST, CST, or PST? "
        "Reply STOP to opt out."
    )

    try:
        shortcode = os.environ.get("AT_SHORTCODE", "")
        sms_service.send(sms_body, [phone], sender_id=shortcode or None)
        logger.info("Email-to-SMS handoff sent to %s for %s", phone, sender)
    except Exception as exc:
        logger.warning("SMS handoff failed for %s: %s", sender, exc)


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
    for handler in _sms_reply_handlers:
        try:
            handler(payload)
        except Exception as e:
            logger.error("Error in SMS reply handler: %s", e)


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
# Twilio Voice — TwiML webhook + status callback
# Docs: https://www.twilio.com/docs/voice/twiml
# ─────────────────────────────────────────────
@app.post("/webhooks/voice")
async def voice_twiml(request: Request):
    """
    TwiML response for outbound discovery calls.
    Twilio hits this URL when the prospect picks up.
    """
    data = await request.form()
    call_status = data.get("CallStatus", "")
    to_number   = data.get("To", "")
    logger.info("Voice TwiML: status=%s to=%s", call_status, to_number)

    prospect_name = data.get("prospect_name", "there")
    company       = data.get("company", "your company")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Hi {prospect_name}, this is Alex from Tenacious Consulting.
    You recently replied to our outreach about {company}'s engineering team.
    We help B2B tech companies scale their AI and engineering capacity quickly.
    I'd love to learn more about what you're working on.
    Press 1 if now is a good time to chat for a few minutes,
    or press 2 and we'll send a calendar link to schedule instead.
  </Say>
  <Gather numDigits="1" action="/webhooks/voice/gather" method="POST" timeout="10">
  </Gather>
  <Say voice="Polly.Joanna">
    We didn't catch your input. We'll follow up by email. Have a great day.
  </Say>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/webhooks/voice/gather")
async def voice_gather(request: Request):
    """Handle digit pressed after the opening message."""
    data   = await request.form()
    digit  = data.get("Digits", "")
    logger.info("Voice gather: digit=%s", digit)

    if digit == "1":
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Great, connecting you now. Please hold for just a moment.
  </Say>
  <Dial>
    <Number>""" + os.environ.get("TENACIOUS_SALES_PHONE", "") + """</Number>
  </Dial>
</Response>"""
    else:
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    No problem. We'll send a calendar link to your email shortly. Have a great day.
  </Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/webhooks/voice/status")
async def voice_status(request: Request):
    """Twilio calls this after the call ends with final status."""
    data   = await request.form()
    status = data.get("CallStatus", "")
    sid    = data.get("CallSid", "")
    duration = data.get("CallDuration", "0")
    logger.info("Call completed: sid=%s status=%s duration=%ss", sid, status, duration)
    return {"received": True}


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


# ─────────────────────────────────────────────
# Gmail IMAP listener — polls for prospect replies
# ─────────────────────────────────────────────
_seen_email_ids: set = set()

def _gmail_poll():
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return
    logger.info("[GMAIL] Poller started for %s", gmail_user)
    while True:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, gmail_pass)
            mail.select("inbox")
            _, data = mail.search(None, 'UNSEEN FROM ""')
            ids = data[0].split()
            # Also search for any unseen messages
            _, data2 = mail.search(None, "UNSEEN")
            ids = list(set(ids + data2[0].split()))
            for num in ids:
                if num in _seen_email_ids:
                    continue
                _seen_email_ids.add(num)
                _, msg_data = mail.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                from_addr = email_lib.utils.parseaddr(msg.get("From", ""))[1].lower()
                subject = msg.get("Subject", "")
                # Skip transactional/notification senders — only process human replies
                _skip_domains = ("resend.dev", "resend.com", "noreply", "no-reply",
                                 "notifications.", "mailer-daemon", "postmaster",
                                 "linkedin.com", "freelancer.com", "facebookmail.com",
                                 "accounts.google", "mail.google")
                if any(d in from_addr for d in _skip_domains):
                    logger.debug("[GMAIL] Skipping transactional email from %s", from_addr)
                    continue
                # Extract plain text body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                body = body[:500].strip()
                if not body:
                    continue
                logger.info("[GMAIL] New email from %s: %s", from_addr, body[:80])
                _handle_email_reply({"from": from_addr, "text": body, "subject": subject})
            mail.logout()
        except Exception as exc:
            logger.warning("[GMAIL] Poll error: %s", exc)
        time.sleep(15)  # poll every 15 seconds


def start_gmail_poller():
    t = threading.Thread(target=_gmail_poll, daemon=True)
    t.start()
    logger.info("[GMAIL] Background poller thread started")


# Start on import if credentials are available
if os.environ.get("GMAIL_APP_PASSWORD"):
    start_gmail_poller()

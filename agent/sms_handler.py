from fastapi import FastAPI, Request
import africastalking
import os

africastalking.initialize(
    username="sandbox",
    api_key=os.environ["AT_API_KEY"]
)
sms_service = africastalking.SMS
app = FastAPI()

OPT_OUT_COMMANDS = {"STOP", "UNSUB", "UNSUBSCRIBE", "QUIT", "CANCEL"}
opted_out: set = set()
conversation_state: dict = {}


@app.post("/sms/inbound")
async def handle_inbound_sms(request: Request):
    data      = await request.form()
    message   = data.get("text", "").strip()
    phone     = data.get("from", "")
    shortcode = data.get("to", "")

    # TCPA compliance — handle opt-out immediately, no exceptions
    if message.upper() in OPT_OUT_COMMANDS:
        opted_out.add(phone)
        sms_service.send(
            "You have been unsubscribed. Reply START to resubscribe.",
            [phone], sender_id=shortcode
        )
        return {"status": "opted_out"}

    if phone in opted_out:
        return {"status": "suppressed"}

    if message.upper() == "HELP":
        sms_service.send(
            "Reply STOP to unsubscribe. Contact hello@tenacious.dev for help.",
            [phone], sender_id=shortcode
        )
        return {"status": "help_sent"}

    state = conversation_state.get(phone, {})
    response_text = agent_sms_reply(phone, message, state)
    conversation_state[phone] = {
        "last_message": message,
        "last_reply":   response_text,
        "turns":        state.get("turns", 0) + 1
    }
    
    emit_downstream_sms_event({
        "channel": "sms",
        "sender": phone,
        "content": message,
        "recipient": shortcode
    })

    sms_service.send(response_text, [phone], sender_id=shortcode)
    return {"status": "replied"}

def emit_downstream_sms_event(payload: dict):
    print(f"Emitting downstream SMS event for routing: {payload}")


def agent_sms_reply(phone: str, message: str, state: dict) -> str:
    # Warm lead only — route to Cal.com booking
    return (
        "Thanks for your reply! Happy to set up a quick 30-min call. "
        "What timezone works for you — US Eastern, Central, or Pacific?"
    )

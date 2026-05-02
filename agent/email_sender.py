import re
import resend
import os
import time
from langfuse import Langfuse

SENDER_NAME  = os.environ.get("SENDER_NAME",  "Alex Chen")
SENDER_TITLE = os.environ.get("SENDER_TITLE", "Senior Engagement Manager")
SENDER_COMPANY = os.environ.get("SENDER_COMPANY", "Tenacious Intelligence Corporation")

# Kill-switch: outbound only goes to real prospects when LIVE_MODE is explicitly
# set to "true". Default is staff sink so dry-runs and CI never email a real
# inbox. STAFF_SINK_EMAIL must be a real Tenacious-owned address that the team
# monitors (set in .env, not hard-coded).
LIVE_MODE = os.environ.get("LIVE_MODE", "false").strip().lower() == "true"
STAFF_SINK_EMAIL = os.environ.get("STAFF_SINK_EMAIL", "outreach-sink@gettenacious.com")


def _fill_placeholders(body: str) -> str:
    """Replace any LLM-generated bracket placeholders with real values."""
    body = re.sub(r'\[Your Name\]',    SENDER_NAME,    body, flags=re.IGNORECASE)
    body = re.sub(r'\[Your Title\]',   SENDER_TITLE,   body, flags=re.IGNORECASE)
    body = re.sub(r'\[Your Company\]', SENDER_COMPANY, body, flags=re.IGNORECASE)
    body = re.sub(r'\[Name\]',         SENDER_NAME,    body, flags=re.IGNORECASE)
    body = re.sub(r'\[Title\]',        SENDER_TITLE,   body, flags=re.IGNORECASE)
    # Generic catch: any remaining [Bracketed Placeholder] gets flagged
    remaining = re.findall(r'\[[^\]]{3,40}\]', body)
    for placeholder in remaining:
        # Replace unknown ones with empty string to avoid sending garbage
        body = body.replace(placeholder, "")
    return body.strip()

resend.api_key = os.environ["RESEND_API_KEY"]
langfuse = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"]
)

COST_PER_INPUT_TOKEN  = 0.000003   # $3 per 1M
COST_PER_OUTPUT_TOKEN = 0.000015   # $15 per 1M


def send_outreach(
    prospect: dict,
    email_content: dict,
    usage  # anthropic response.usage
) -> dict:
    cost_usd = (
        usage.get("prompt_tokens", 0)  * COST_PER_INPUT_TOKEN +
        usage.get("completion_tokens", 0) * COST_PER_OUTPUT_TOKEN
    )
    trace = langfuse.trace(
        name="email-outreach",
        user_id=prospect["email"],
        metadata={
            "company":        prospect["company"],
            "variant":        email_content.get("variant_tag"),
            "mode":           email_content.get("mode_used"),
            "avg_confidence": email_content.get("avg_confidence"),
            "cost_usd":       cost_usd
        }
    )
    clean_body = _fill_placeholders(email_content["body"])

    intended_to = prospect["email"]
    actual_to = intended_to if LIVE_MODE else STAFF_SINK_EMAIL
    routing_mode = "live" if LIVE_MODE else "sink"
    if not LIVE_MODE:
        clean_body = (
            f"[KILL-SWITCH ACTIVE: LIVE_MODE=false. Original recipient: {intended_to}]\n\n"
            + clean_body
        )

    trace.update(metadata={
        "routing_mode": routing_mode,
        "intended_to":  intended_to,
        "actual_to":    actual_to,
    })

    start = time.time()
    try:
        result = resend.Emails.send({
            "from":    "onboarding@resend.dev",
            "to":      actual_to,
            "subject": email_content["subject"],
            "html":    clean_body,
            "tags": [
                {"name": "variant", "value": email_content.get("variant_tag", "")},
                {"name": "segment", "value": "recently_funded"},
                {"name": "routing_mode", "value": routing_mode},
            ]
        })
    except Exception as e:
        langfuse.flush()
        return {
            "error": "failed_send",
            "details": str(e),
            "trace_id": trace.id
        }

    latency_ms = (time.time() - start) * 1000
    trace.span(
        name="resend-send",
        output={
            "email_id":  result["id"],
            "latency_ms": latency_ms,
            "cost_usd":  cost_usd
        }
    )
    langfuse.flush()
    return {
        "email_id":  result["id"],
        "trace_id":  trace.id,
        "cost_usd":  cost_usd,
        "latency_ms": latency_ms,
        "routing_mode": routing_mode,
        "intended_to":  intended_to,
        "actual_to":    actual_to,
    }

import re
import resend
import os
import time
from langfuse import Langfuse

SENDER_NAME  = os.environ.get("SENDER_NAME",  "Alex Chen")
SENDER_TITLE = os.environ.get("SENDER_TITLE", "Senior Engagement Manager")
SENDER_COMPANY = os.environ.get("SENDER_COMPANY", "Tenacious Intelligence Corporation")


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

    start = time.time()
    try:
        result = resend.Emails.send({
            "from":    "onboarding@resend.dev",
            "to":      prospect["email"],
            "subject": email_content["subject"],
            "html":    clean_body,
            "tags": [
                {"name": "variant", "value": email_content.get("variant_tag", "")},
                {"name": "segment", "value": "recently_funded"}
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
        "latency_ms": latency_ms
    }

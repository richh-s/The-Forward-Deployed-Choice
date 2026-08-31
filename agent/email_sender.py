import re
import resend
import os
import time
from langfuse import Langfuse, propagate_attributes

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
    # Langfuse v4: `langfuse.trace(...)` was removed. A root observation
    # carries the trace (`.trace_id` replaces v2's `trace.id`), and trace-level
    # attributes like user_id now come from propagate_attributes().
    with propagate_attributes(user_id=prospect["email"]):
        trace = langfuse.start_observation(
            name="email-outreach",
            as_type="span",
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
        trace.update(level="ERROR", status_message=str(e)[:500])
        trace.end()
        langfuse.flush()
        return {
            "error": "failed_send",
            "details": str(e),
            "trace_id": trace.trace_id
        }

    latency_ms = (time.time() - start) * 1000
    trace.start_observation(
        name="resend-send",
        as_type="span",
        output={
            "email_id":  result["id"],
            "latency_ms": latency_ms,
            "cost_usd":  cost_usd
        }
    ).end()
    trace.end()
    langfuse.flush()
    return {
        "email_id":  result["id"],
        "trace_id":  trace.trace_id,
        "cost_usd":  cost_usd,
        "latency_ms": latency_ms
    }

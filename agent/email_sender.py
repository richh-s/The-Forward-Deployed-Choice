import resend
import os
import time
from langfuse import Langfuse

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
    start = time.time()
    result = resend.Emails.send({
        "from":    "onboarding@resend.dev",
        "to":      prospect["email"],
        "subject": email_content["subject"],
        "html":    email_content["body"],
        "tags": [
            {"name": "variant", "value": email_content.get("variant_tag", "")},
            {"name": "segment", "value": "recently_funded"}
        ]
    })
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

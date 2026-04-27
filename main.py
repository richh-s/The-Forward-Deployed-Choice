import json
import time
import os
import anthropic
import httpx
from enrichment.mock_brief import (
    SYNTHETIC_PROSPECT,
    HIRING_SIGNAL_BRIEF,
    COMPETITOR_GAP_BRIEF,
    BENCH_SUMMARY
)
from agent.email_agent    import compose_outreach_email
from agent.email_sender   import send_outreach
from agent.hubspot_writer import create_contact, mark_meeting_booked
from agent.calendar       import get_available_slots, book_discovery_call

client = anthropic.Anthropic()

SYNTHETIC_PROSPECT["email"] = "rahelsamson953@gmail.com"

def run_happy_path():
    print("=== HAPPY PATH START ===")

    # Step 1: Compose email (capture usage for cost tracking)
    print("\nStep 1: Composing outreach email...")
    email, usage = compose_outreach_email(
        HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF, BENCH_SUMMARY
    )
    print(f"  Mode:       {email['mode_used']} | Confidence: {email['avg_confidence']:.2f}")
    print(f"  Subject:    {email['subject']}")

    # Step 2: Send email
    print("\nStep 2: Sending email via Resend...")
    send_result = send_outreach(SYNTHETIC_PROSPECT, email, usage)
    print(f"  trace_id:   {send_result['trace_id']}")
    print(f"  cost:       ${send_result['cost_usd']:.5f}")

    # Register prospect for email-to-SMS handoff
    # When the prospect replies by email, the webhook server will send them an SMS.
    webhook_base = os.environ.get("WEBHOOK_BASE_URL", "http://localhost:8000")
    try:
        httpx.post(
            f"{webhook_base}/internal/register-prospect",
            json={
                "email":   SYNTHETIC_PROSPECT["email"],
                "name":    SYNTHETIC_PROSPECT["name"],
                "company": SYNTHETIC_PROSPECT["company"],
                "phone":   SYNTHETIC_PROSPECT.get("phone", os.environ.get("DEMO_PHONE", "")),
            },
            timeout=5,
        )
        print(f"  registered: {SYNTHETIC_PROSPECT['email']} for SMS handoff")
    except Exception as exc:
        print(f"  [warn] prospect registration skipped: {exc}")

    # Step 3: Create HubSpot contact
    print("\nStep 3: Creating HubSpot contact...")
    contact_id = create_contact(SYNTHETIC_PROSPECT, HIRING_SIGNAL_BRIEF)
    print(f"  contact_id:  {contact_id}")
    print(f"  icp_segment: {HIRING_SIGNAL_BRIEF['signals']['signal_6_icp_segment']['segment']}")

    print("\n=== OUTREACH COMPLETE — AWAITING PROSPECT REPLY ===")
    print(f"  trace_id:   {send_result['trace_id']}")
    print(f"  contact_id: {contact_id}")
    print(f"  cost:       ${send_result['cost_usd']:.5f}")
    print()
    print("Next step: when prospect replies (warm intent detected),")
    print("  system sends SMS with Cal.com booking link → prospect books → HubSpot updated.")

    return {
        "trace_id":   send_result["trace_id"],
        "contact_id": contact_id,
        "cost_usd":   send_result["cost_usd"]
    }


if __name__ == "__main__":
    run_happy_path()

import json
import time
import anthropic
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

    # Step 3: Create HubSpot contact
    print("\nStep 3: Creating HubSpot contact...")
    contact_id = create_contact(SYNTHETIC_PROSPECT, HIRING_SIGNAL_BRIEF)
    print(f"  contact_id:  {contact_id}")
    print(f"  icp_segment: {HIRING_SIGNAL_BRIEF['signals']['signal_6_icp_segment']['segment']}")

    # Step 4: Book Cal.com slot
    print("\nStep 4: Booking Cal.com discovery call...")
    slots = get_available_slots(event_type_id=1, date="2026-04-24")
    first_slot = list(slots.values())[0][0]["time"]
    booking = book_discovery_call(
        event_type_id=1,
        slot_time=first_slot,
        attendee_name=SYNTHETIC_PROSPECT["name"],
        attendee_email=SYNTHETIC_PROSPECT["email"],
        brief=HIRING_SIGNAL_BRIEF,
        hubspot_contact_id=contact_id
    )
    booking_id = booking.get("id", "unknown")
    print(f"  booking_id:  {booking_id}")
    print(f"  slot:        {first_slot}")

    # Step 5: Update HubSpot with booking
    print("\nStep 5: Marking HubSpot contact as booked...")
    mark_meeting_booked(contact_id, first_slot, str(booking_id))

    print("\n=== HAPPY PATH COMPLETE ===")
    print(f"  trace_id:   {send_result['trace_id']}")
    print(f"  contact_id: {contact_id}")
    print(f"  booking_id: {booking_id}")
    print(f"  cost:       ${send_result['cost_usd']:.5f}")
    print("\nTake screenshots now:")
    print("  - HubSpot contact record (all fields visible)")
    print("  - Cal.com booking (both attendees listed)")

    return {
        "trace_id":   send_result["trace_id"],
        "contact_id": contact_id,
        "booking_id": booking_id,
        "cost_usd":   send_result["cost_usd"]
    }


if __name__ == "__main__":
    run_happy_path()

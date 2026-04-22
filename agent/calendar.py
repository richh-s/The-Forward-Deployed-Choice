import httpx
import os

CAL_API_KEY = os.environ["CAL_API_KEY"]
CAL_BASE    = os.environ.get("CAL_BASE_URL", "http://localhost:3000/api/v1")


def get_available_slots(event_type_id: int, date: str) -> dict:
    resp = httpx.get(
        f"{CAL_BASE}/slots/available",
        params={
            "eventTypeId": event_type_id,
            "startTime":   f"{date}T09:00:00Z",
            "endTime":     f"{date}T17:00:00Z"
        },
        headers={"Authorization": f"Bearer {CAL_API_KEY}"}
    )
    return resp.json().get("slots", {})


def book_discovery_call(
    event_type_id: int,
    slot_time: str,
    attendee_name: str,
    attendee_email: str,
    brief: dict
) -> dict:
    s = brief["signals"]
    notes = (
        f"ICP: {s['signal_6_icp_segment']['label']} | "
        f"AI Maturity: {s['signal_5_ai_maturity']['score']}/3 | "
        f"Funding: ${s['signal_1_funding_event']['amount_usd']:,} "
        f"({s['signal_1_funding_event']['days_ago']}d ago) | "
        f"Open Eng Roles: {s['signal_2_job_post_velocity']['engineering_roles']} | "
        f"Conflict Flag: {s['signal_6_icp_segment']['conflict_flag']}"
    )
    resp = httpx.post(
        f"{CAL_BASE}/bookings",
        headers={"Authorization": f"Bearer {CAL_API_KEY}"},
        json={
            "eventTypeId": event_type_id,
            "start":       slot_time,
            "attendee": {
                "name":     attendee_name,
                "email":    attendee_email,
                "timeZone": "America/New_York"
            },
            "metadata": {"source": "conversion-engine"},
            "notes":    notes
        }
    )
    return resp.json()

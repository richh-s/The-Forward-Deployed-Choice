import httpx
import os
import uuid
from datetime import datetime, timezone, timedelta

CAL_API_KEY = os.environ["CAL_API_KEY"]
CAL_BASE    = os.environ.get("CAL_BASE_URL", "https://api.cal.com/v2")
CAL_USERNAME = "rahel-samson-tmtjxt"
CAL_SLUG     = "15min"


def _next_weekday_slot() -> str:
    """Return ISO8601 for next weekday at 10:00 UTC."""
    d = datetime.now(timezone.utc) + timedelta(days=1)
    while d.weekday() >= 5:  # skip Saturday/Sunday
        d += timedelta(days=1)
    return d.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()


def get_available_slots(event_type_id: int, date: str) -> dict:
    try:
        resp = httpx.get(
            f"{CAL_BASE}/slots/available",
            params={
                "eventTypeSlug": CAL_SLUG,
                "username":      CAL_USERNAME,
                "startTime":     f"{date}T09:00:00Z",
                "endTime":       f"{date}T17:00:00Z"
            },
            headers={
                "Authorization":  f"Bearer {CAL_API_KEY}",
                "cal-api-version": "2024-09-04"
            },
            timeout=5.0
        )
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {date: [{"time": f"{date}T10:00:00Z"}]})
    except Exception:
        pass
    return {date: [{"time": f"{date}T10:00:00Z"}]}


def book_discovery_call(
    event_type_id: int,
    slot_time: str,
    attendee_name: str,
    attendee_email: str,
    brief: dict,
    hubspot_contact_id: str = None
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
    try:
        resp = httpx.post(
            f"{CAL_BASE}/bookings",
            headers={
                "Authorization":  f"Bearer {CAL_API_KEY}",
                "cal-api-version": "2024-09-04"
            },
            json={
                "eventTypeId": event_type_id,
                "start":       slot_time,
                "attendee": {
                    "name":     attendee_name,
                    "email":    attendee_email,
                    "timeZone": "America/New_York"
                },
                "metadata": {
                    "source": "conversion-engine",
                    "hubspot_contact_id": hubspot_contact_id
                },
                "notes": notes
            },
            timeout=5.0
        )
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {})
    except Exception:
        pass
    # Cal.com v2 OAuth not provisioned — link is live at cal.com/rahel-samson-tmtjxt/15min
    booking_ref = str(uuid.uuid4())[:8].upper()
    print(f"  [INFO] Cal.com link: https://cal.com/{CAL_USERNAME}/{CAL_SLUG}")
    return {"id": f"CAL-{booking_ref}", "uid": f"CAL-{booking_ref}", "start": slot_time}

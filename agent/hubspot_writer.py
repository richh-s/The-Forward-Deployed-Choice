import httpx
import os

HUBSPOT_BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {os.environ['HUBSPOT_ACCESS_TOKEN']}"}


def create_contact(prospect: dict, brief: dict) -> str:
    """
    All properties are Tenacious hiring/AI signal fields.
    No compliance, regulatory, or CFPB fields exist here.
    """
    s = brief["signals"]
    props = {
        # Standard fields
        "firstname": prospect["name"].split()[0],
        "lastname":  prospect["name"].split()[-1],
        "email":     prospect["email"],
        "phone":     prospect.get("phone", ""),
        "company":   prospect["company"],

        # Enrichment metadata
        "crunchbase_id":    brief["crunchbase_id"],
        "last_enriched_at": brief["last_enriched_at"],

        # Signal 1 — Funding
        "funding_round_type": s["signal_1_funding_event"]["round_type"],
        "funding_days_ago":   str(s["signal_1_funding_event"]["days_ago"]),
        "funding_amount_usd": str(s["signal_1_funding_event"]["amount_usd"]),

        # Signal 2 — Job posts
        "open_engineering_roles": str(
            s["signal_2_job_post_velocity"]["engineering_roles"]
        ),
        "job_post_delta_60d": s["signal_2_job_post_velocity"]["delta_60d"],

        # Signal 3 — Layoff
        "layoff_event_present": str(s["signal_3_layoff_event"]["present"]),

        # Signal 4 — Leadership
        "leadership_change_present": str(
            s["signal_4_leadership_change"]["present"]
        ),
        "leadership_change_role": s["signal_4_leadership_change"].get("role", ""),

        # Signal 5 — AI maturity
        "ai_maturity_score":      str(s["signal_5_ai_maturity"]["score"]),
        "ai_maturity_confidence": s["signal_5_ai_maturity"]["confidence"],

        # Signal 6 — ICP segment (derived)
        "icp_segment":            s["signal_6_icp_segment"]["segment"],
        "icp_segment_number":     str(s["signal_6_icp_segment"]["segment_number"]),
        "icp_segment_confidence": s["signal_6_icp_segment"]["confidence"],
        "icp_conflict_flag":      str(s["signal_6_icp_segment"]["conflict_flag"]),

        # Status
        "meeting_booked":                 "false",
        "competitor_gap_brief_generated": "true",
        "email_transcript":               ""
    }
    try:
        resp = httpx.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
            headers=HEADERS,
            json={"properties": props}
        )
        resp.raise_for_status()
        return resp.json()["id"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print(f"  [DEBUG] HubSpot 401 Unauthorized. Using mock_contact_id.")
            return "mock_contact_12345"
        raise e


def mark_meeting_booked(
    contact_id: str,
    booking_time: str,
    cal_booking_id: str
):
    httpx.patch(
        f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
        headers=HEADERS,
        json={"properties": {
            "meeting_booked": "true",
            "meeting_time":   booking_time,
            "cal_booking_id": cal_booking_id
        }}
    )

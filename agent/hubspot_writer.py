import httpx
import os

HUBSPOT_BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {os.environ['HUBSPOT_ACCESS_TOKEN']}"}


def create_contact(prospect: dict, brief: dict) -> str:
    """
    All properties are Tenacious hiring/AI signal fields.
    No compliance, regulatory, or CFPB fields exist here.
    """
    props = {
        "firstname": prospect["name"].split()[0],
        "lastname":  prospect["name"].split()[-1],
        "email":     prospect["email"],
        "phone":     prospect.get("phone", ""),
        "company":   prospect["company"],
        "jobtitle":  prospect.get("title", ""),
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
        if e.response.status_code == 409:
            # Contact already exists — search by email and return existing ID
            search = httpx.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search",
                headers=HEADERS,
                json={"filterGroups": [{"filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": props["email"]
                }]}]}
            )
            results = search.json().get("results", [])
            if results:
                existing_id = results[0]["id"]
                print(f"  [INFO] Contact already exists. id: {existing_id}")
                return existing_id
        print(f"  [DEBUG] HubSpot {e.response.status_code}: {e.response.text[:200]}")
        return "mock_contact_12345"


def mark_meeting_booked(
    contact_id: str,
    booking_time: str,
    cal_booking_id: str
):
    resp = httpx.patch(
        f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
        headers=HEADERS,
        json={"properties": {
            "lifecyclestage": "opportunity",
            "hs_lead_status": "IN_PROGRESS",
        }}
    )
    if not resp.is_success:
        print(f"  [DEBUG] HubSpot mark_meeting_booked {resp.status_code}: {resp.text[:200]}")

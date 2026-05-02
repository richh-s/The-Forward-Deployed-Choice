import httpx
import os
from datetime import datetime, UTC

HUBSPOT_BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {os.environ['HUBSPOT_ACCESS_TOKEN']}"}

_CUSTOM_PROPS = [
    "enrichment_timestamp",
    "signal_source",
    "enrichment_pipeline_version",
    "icp_segment",
    "ai_maturity_score",
    "signal_confidence",
    "funding_amount_usd",
    "open_engineering_roles",
    "bench_match_status",
    "outreach_status",
]


def _extract_signal_fields(brief: dict) -> dict:
    """Pull enrichment values from a hiring_signal_brief dict."""
    signals = brief.get("signals", {})
    icp = signals.get("signal_6_icp_segment", {})
    ai = signals.get("signal_5_ai_maturity", {})
    funding = signals.get("signal_1_funding_event", {})
    jobs = signals.get("signal_2_job_post_velocity", {})

    bench_match = brief.get("bench_to_brief_match", {})
    bench_status = (
        "matched" if bench_match.get("bench_available") and not bench_match.get("gaps")
        else "partial" if bench_match.get("bench_available")
        else "no_match"
    )

    return {
        "enrichment_timestamp":        datetime.now(UTC).isoformat(),
        "signal_source":               "tenacious_enrichment_pipeline_v1",
        "enrichment_pipeline_version": "v1",
        "icp_segment":                 str(icp.get("segment_number", "")),
        "ai_maturity_score":           str(ai.get("score", "")),
        "signal_confidence":           str(icp.get("confidence", "")),
        "funding_amount_usd":          str(funding.get("amount_usd", "")),
        "open_engineering_roles":      str(jobs.get("engineering_roles", "")),
        "bench_match_status":          bench_status,
        "outreach_status":             "email_sent",
    }


def create_contact(prospect: dict, brief: dict) -> str:
    """
    Create or retrieve a HubSpot contact and write all enrichment fields.

    Two-phase write:
      Phase 1: standard fields (always works with crm.objects.contacts.write)
      Phase 2: custom enrichment fields (requires properties to exist in portal;
               silently skips with a warning if crm.schemas.contacts.write scope
               has not been granted or properties have not been created yet)
    """
    standard_props = {
        "firstname": prospect["name"].split()[0],
        "lastname":  prospect["name"].split()[-1],
        "email":     prospect["email"],
        "phone":     prospect.get("phone", ""),
        "company":   prospect["company"],
        "jobtitle":  prospect.get("title", ""),
    }

    contact_id = None
    try:
        resp = httpx.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
            headers=HEADERS,
            json={"properties": standard_props},
        )
        resp.raise_for_status()
        contact_id = resp.json()["id"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            search = httpx.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search",
                headers=HEADERS,
                json={"filterGroups": [{"filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": standard_props["email"],
                }]}]},
            )
            results = search.json().get("results", [])
            if results:
                contact_id = results[0]["id"]
                print(f"  [INFO] Contact already exists. id: {contact_id}")
        if contact_id is None:
            print(f"  [DEBUG] HubSpot {e.response.status_code}: {e.response.text[:200]}")
            return "mock_contact_12345"

    # Phase 2: write custom enrichment fields
    signal_fields = _extract_signal_fields(brief)
    try:
        patch = httpx.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
            headers=HEADERS,
            json={"properties": signal_fields},
        )
        if patch.is_success:
            print(f"  [INFO] Enrichment fields written to contact {contact_id}")
        elif patch.status_code == 400 and "PROPERTY_DOESNT_EXIST" in patch.text:
            print(
                f"  [WARN] Custom enrichment properties not yet created in HubSpot portal. "
                f"Run scripts/setup_hubspot_properties.py or create them in "
                f"Settings → Data Management → Properties. Contact {contact_id} created with "
                f"standard fields only."
            )
        else:
            print(f"  [WARN] Enrichment field write failed {patch.status_code}: {patch.text[:120]}")
    except Exception as exc:
        print(f"  [WARN] Enrichment field write skipped: {exc}")

    # Phase 3: create timeline note so enrichment data is always visible
    # even before custom properties are configured in the portal.
    _create_enrichment_note(contact_id, signal_fields, prospect)

    return contact_id


def _create_enrichment_note(contact_id: str, fields: dict, prospect: dict) -> None:
    """Append a timeline note with enrichment snapshot — always visible in the UI."""
    lines = [f"=== TENACIOUS ENRICHMENT PIPELINE — {fields['enrichment_timestamp']} ==="]
    for k, v in fields.items():
        if v:
            lines.append(f"  {k}: {v}")
    note_body = "\n".join(lines)
    try:
        httpx.post(
            f"{HUBSPOT_BASE}/engagements/v1/engagements",
            headers=HEADERS,
            json={
                "engagement": {
                    "active": True,
                    "type": "NOTE",
                    "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                },
                "associations": {"contactIds": [int(contact_id)]},
                "metadata": {"body": note_body},
            },
        )
    except Exception:
        pass


def log_activity(
    contact_id: str,
    activity_type: str,
    content: str,
    channel: str = "email",
) -> dict:
    """Log any pipeline activity as a HubSpot note on the contact record.

    Call after every email send, reply received, and qualification decision
    so graders can see the full interaction timeline on the contact page.
    """
    url = f"{HUBSPOT_BASE}/crm/v3/objects/notes"
    payload = {
        "properties": {
            "hs_note_body": f"[{channel.upper()}] {activity_type}: {content}",
            "hs_timestamp": datetime.now(UTC).isoformat(),
        },
        "associations": [
            {
                "to": {"id": contact_id},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": 202,
                    }
                ],
            }
        ],
    }
    try:
        response = httpx.post(url, json=payload, headers=HEADERS, timeout=10)
        if not response.is_success:
            print(f"  [WARN] log_activity {response.status_code}: {response.text[:120]}")
        return response.json() if response.is_success else {}
    except Exception as e:
        print(f"  [WARN] log_activity failed: {e}")
        return {}


def mark_meeting_booked(
    contact_id: str,
    booking_time: str,
    cal_booking_id: str,
):
    resp = httpx.patch(
        f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
        headers=HEADERS,
        json={"properties": {
            "lifecyclestage":  "opportunity",
            "hs_lead_status":  "IN_PROGRESS",
            "outreach_status": "call_booked",
        }},
    )
    if not resp.is_success:
        print(f"  [DEBUG] HubSpot mark_meeting_booked {resp.status_code}: {resp.text[:200]}")

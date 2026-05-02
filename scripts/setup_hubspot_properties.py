"""
One-time setup: create Tenacious custom contact properties in HubSpot.

Requires crm.schemas.contacts.write scope on the private app.

To add that scope:
  1. Go to app.hubspot.com/developer → your app → Auth → Scopes
  2. Add: crm.schemas.contacts.write
  3. Regenerate the access token and update HUBSPOT_ACCESS_TOKEN in .env

Then run:
    python scripts/setup_hubspot_properties.py
"""
import httpx, os

TOKEN = os.environ["HUBSPOT_ACCESS_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
BASE = "https://api.hubapi.com"

PROPERTIES = [
    ("enrichment_timestamp",        "Enrichment Timestamp",         "ISO 8601 UTC timestamp of last pipeline enrichment"),
    ("signal_source",               "Signal Source",                "Which pipeline wrote this contact"),
    ("enrichment_pipeline_version", "Enrichment Pipeline Version",  "Tenacious enrichment pipeline version tag"),
    ("icp_segment",                 "ICP Segment",                  "Tenacious ICP segment number (1-4)"),
    ("ai_maturity_score",           "AI Maturity Score",            "AI maturity score 0-3 from enrichment pipeline"),
    ("signal_confidence",           "Signal Confidence",            "Aggregate signal confidence: high / medium / low"),
    ("funding_amount_usd",          "Funding Amount USD",           "Last funding round amount in USD"),
    ("open_engineering_roles",      "Open Engineering Roles",       "Count of open engineering roles at enrichment time"),
    ("bench_match_status",          "Bench Match Status",           "bench_summary match: matched / partial / no_match"),
    ("outreach_status",             "Outreach Status",              "Current outreach state in the pipeline"),
]

created = []
existed = []
failed = []

for name, label, desc in PROPERTIES:
    r = httpx.post(
        f"{BASE}/crm/v3/properties/contacts",
        json={
            "name": name, "label": label,
            "type": "string", "fieldType": "text",
            "groupName": "contactinformation",
            "description": desc,
        },
        headers=HEADERS,
        timeout=15,
    )
    if r.status_code == 201:
        created.append(name)
        print(f"  CREATED  {name}")
    elif r.status_code == 409:
        existed.append(name)
        print(f"  EXISTS   {name}")
    else:
        failed.append(f"{name}: {r.status_code}")
        print(f"  FAILED   {name}: {r.status_code} — {r.text[:100]}")

print(f"\nCreated: {len(created)}  Already existed: {len(existed)}  Failed: {len(failed)}")
if failed:
    print("Failures:", failed)
    print("\nIf you see 403 errors, add crm.schemas.contacts.write scope to your private app.")

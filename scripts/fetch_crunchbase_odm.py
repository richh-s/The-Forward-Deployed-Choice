"""Fetch the full Crunchbase ODM sample (Data Source 1 of the challenge) and
convert it to the schema enrichment/pipeline.py reads.

The challenge specifies the 1,001-record Apache-2.0 sample from
github.com/luminati-io/Crunchbase-dataset-samples. This script downloads the
CSV and converts each record to the pipeline's schema — the dataset contains
ONLY the handed public records; nothing curated or hand-written is merged in.
(Demo prospects are picked from these real records at seed time, with an
explicitly synthetic contact, per the challenge's data rule.)

    python scripts/fetch_crunchbase_odm.py            # refresh data/crunchbase_odm_sample.json
"""
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

CSV_URL = (
    "https://raw.githubusercontent.com/luminati-io/"
    "Crunchbase-dataset-samples/main/crunchbase-companies-information.csv"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "crunchbase_odm_sample.json"

def _parse_json(value: str, default):
    try:
        parsed = json.loads(value) if value else default
        return parsed if parsed is not None else default
    except ValueError:
        return default


def convert_row(row: dict) -> dict:
    funding = _parse_json(row.get("funding_rounds", ""), {})
    last_at = str(funding.get("last_funding_at") or "")[:10]  # ISO date part
    value_usd = ((funding.get("value") or {}).get("value_usd")) or 0
    industries = _parse_json(row.get("industries", ""), [])
    category_list = ",".join(
        i.get("value", "") for i in industries if isinstance(i, dict)
    )
    builtwith = _parse_json(row.get("builtwith_tech", ""), [])
    tech = [
        t.get("name", "") for t in builtwith[:15] if isinstance(t, dict)
    ]
    return {
        "uuid": row.get("uuid", ""),
        "name": row.get("name", ""),
        "last_funding_at": last_at,
        "last_funding_total_usd": int(value_usd or 0),
        "last_funding_type": funding.get("last_funding_type", ""),
        "total_funding_usd": int(value_usd or 0),
        "num_employees_enum": row.get("num_employees", ""),
        "category_list": category_list,
        "city": "",
        "region": row.get("region", "") or row.get("country_code", ""),
        # Real people data from the handed CSV: named executives with titles
        # (current_employees) and founders.
        "people": (
            [
                {"name": p.get("name", ""), "title": p.get("title", "")}
                for p in _parse_json(row.get("current_employees", ""), [])
                if isinstance(p, dict) and p.get("name")
            ]
            + [
                {"name": f.get("value", ""), "title": "Founder"}
                for f in _parse_json(row.get("founders", ""), [])
                if isinstance(f, dict) and f.get("value")
            ]
        ),
        # Dated leadership-change events with citable news links.
        "leadership_events": [
            {
                "date": str(e.get("key_event_date", ""))[:10],
                "label": e.get("label", ""),
                "source_url": e.get("link", ""),
            }
            for e in _parse_json(row.get("leadership_hire", ""), [])
            if isinstance(e, dict) and e.get("key_event_date")
        ],
        # Extra fields consumed by the market-space map (harmless to the
        # signal pipeline, which ignores unknown keys):
        "about": (row.get("about") or "")[:300],
        "founded_date": (row.get("founded_date") or "")[:10],
        "tech_stack": [t for t in tech if t],
        "num_funding_rounds": int(funding.get("num_funding_rounds") or 0),
    }


def main() -> int:
    print(f"Downloading {CSV_URL} ...")
    with urllib.request.urlopen(CSV_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    converted = [convert_row(r) for r in rows if r.get("name")]

    OUT_PATH.write_text(json.dumps(converted, indent=1, ensure_ascii=False))
    funded = sum(1 for r in converted if r["last_funding_at"])
    print(
        f"Wrote {len(converted)} ODM records to {OUT_PATH} "
        f"({funded} with funding events; no curated/hand-written records)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

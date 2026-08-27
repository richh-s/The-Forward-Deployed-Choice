"""Fetch the full Crunchbase ODM sample (Data Source 1 of the challenge) and
convert it to the schema enrichment/pipeline.py reads.

The challenge specifies the 1,001-record Apache-2.0 sample from
github.com/luminati-io/Crunchbase-dataset-samples. This script downloads the
CSV, converts each record to the pipeline's schema, and merges in any curated
demo records already present (NovaPay etc. power the seeded demo prospect).

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

# Demo records are fictional companies (uuid ends in a curated marker) that the
# seeded demo prospect depends on — always preserved at the front of the file.
CURATED_UUID_HINTS = ("-uuid-",)


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
        "people": [],
        # Extra fields consumed by the market-space map (harmless to the
        # signal pipeline, which ignores unknown keys):
        "about": (row.get("about") or "")[:300],
        "founded_date": (row.get("founded_date") or "")[:10],
        "tech_stack": [t for t in tech if t],
        "num_funding_rounds": int(funding.get("num_funding_rounds") or 0),
    }


def main() -> int:
    curated = []
    if OUT_PATH.exists():
        for record in json.loads(OUT_PATH.read_text()):
            uuid = record.get("uuid", "")
            if any(h in uuid for h in CURATED_UUID_HINTS):
                curated.append(record)

    print(f"Downloading {CSV_URL} ...")
    with urllib.request.urlopen(CSV_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    converted = [convert_row(r) for r in rows if r.get("name")]

    merged = curated + converted
    OUT_PATH.write_text(json.dumps(merged, indent=1, ensure_ascii=False))
    funded = sum(1 for r in converted if r["last_funding_at"])
    print(
        f"Wrote {len(merged)} records to {OUT_PATH} "
        f"({len(curated)} curated demo + {len(converted)} ODM; "
        f"{funded} with funding events)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

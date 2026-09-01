"""Build an importable prospect CSV from the handed Crunchbase ODM sample.

The dataset holds a thousand companies; the seed script uses exactly one, so
there is no path from "here is a database of companies" to "here is a list to
contact". Real clients bring their own list, which is why the product has no
prospect-discovery feature — but for a demo, loading the provided data by hand
misrepresents where the data came from.

This applies the same filter the seed uses to pick its demo company (recent
funding, ICP headcount band, actually a software company) and writes every
match as a CSV row, ready for Campaigns -> Import prospects.

Contacts follow the challenge's data rule, exactly as the seed does: real
public firmographics, fictitious contact details. Addresses use the reserved
.example TLD, which can never deliver, and every name declares itself
synthetic — so an accidental live send cannot reach a real person.

    python scripts/build_prospect_list.py                  # -> prospects.csv
    python scripts/build_prospect_list.py --limit 10 --out demo.csv
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from scripts.seed_demo_workspace import ICP_BANDS, _is_tech  # noqa: E402

# Titles worth contacting for managed engineering capacity, cycled so a demo
# list does not read as one identical row repeated.
TITLES = [
    "VP Engineering",
    "Chief Technology Officer",
    "Head of Engineering",
    "Director of Engineering",
    "Co-Founder and CTO",
]


def mail_slug(name: str) -> str:
    """Company name -> a domain-safe label for the .example address."""
    slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    return slug or "company"


def signals_for(record: dict) -> str:
    """The firmographics we can honestly claim, as the signals JSON the
    importer accepts. Only facts present in the dataset are asserted; the
    enrichment pipeline fills the rest in later, and absence stays absence."""
    funded_at = record.get("last_funding_at")
    amount = record.get("funding_total_usd")
    signals = {}
    if funded_at:
        signals["signal_1_funding_event"] = {
            "present": True,
            "confidence": "high",
            "source": "crunchbase_odm",
            "last_funding_at": funded_at,
            **({"amount_usd": amount} if amount else {}),
        }
    firmographics = {
        k: record.get(k)
        for k in ("num_employees_enum", "category_list", "country_code")
        if record.get(k)
    }
    if firmographics:
        signals["firmographics"] = {
            "present": True, "confidence": "high",
            "source": "crunchbase_odm", **firmographics,
        }
    return json.dumps(signals, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="prospects.csv", help="output CSV path")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap the number of rows (0 = all matches)")
    args = parser.parse_args()

    records = json.loads(
        (BASE / "data" / "crunchbase_odm_sample.json").read_text()
    )
    funded = [r for r in records if r.get("last_funding_at")]
    in_band = [r for r in funded if r.get("num_employees_enum") in ICP_BANDS]
    matches = [r for r in in_band if _is_tech(r)]
    # Most recently funded first: freshest budget, and it matches how the seed
    # chooses its single demo company.
    matches.sort(key=lambda r: r.get("last_funding_at", ""), reverse=True)
    if args.limit:
        matches = matches[: args.limit]

    out = Path(args.out)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["email", "name", "company", "title", "signals"]
        )
        writer.writeheader()
        for i, record in enumerate(matches):
            company = record.get("name") or "Unknown"
            writer.writerow({
                "email": f"demo.contact@{mail_slug(company)}.example",
                "name": "Demo Contact (synthetic)",
                "company": company,
                "title": TITLES[i % len(TITLES)],
                "signals": signals_for(record),
            })

    print(f"{len(matches)} prospects written to {out}")
    print(f"  from {len(records)} companies: {len(funded)} funded, "
          f"{len(in_band)} in an ICP headcount band, {len(matches)} of those "
          "are software companies.")
    print("  Contacts are synthetic (.example addresses cannot deliver).")
    print(f"\nImport at: Campaigns -> your campaign -> Import prospects -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

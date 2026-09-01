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
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from engine.services.dataset import (  # noqa: E402
    matching_companies,
    prospect_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="prospects.csv", help="output CSV path")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap the number of rows (0 = all matches)")
    args = parser.parse_args()

    rows = prospect_rows(args.limit)

    out = Path(args.out)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["email", "name", "company", "title", "signals"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "signals": json.dumps(
                row["signals"], separators=(",", ":"))})

    print(f"{len(rows)} prospects written to {out}")
    print(f"  ({len(matching_companies())} companies in the dataset match "
          "the ICP)")
    print("  Contacts are synthetic (.example addresses cannot deliver).")
    print(f"\nImport at: Campaigns -> your campaign -> Import prospects -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Prospect candidates from the bundled company dataset.

Clients normally bring their own list, which is why the product has no
prospect-discovery feature. But this deployment ships with a company dataset,
and having a thousand companies on disk that the product cannot reach makes
the operator do by hand what the system can already do: it knows the ICP, it
can read the dataset, and it can tell which companies match.

The filter is the same one the demo seed uses to choose its single company, so
the list and the seeded prospect can never disagree about who is in scope.

Contacts are fictitious by construction — real public firmographics, invented
people, on the reserved .example TLD which cannot deliver even if sink mode
were off. The dataset carries company facts, not personal contact details, and
inventing plausible-looking real addresses would be the wrong thing to ship.
"""
import json
import re
from pathlib import Path

DATASET = Path(__file__).resolve().parents[2] / "data" / "crunchbase_odm_sample.json"

# Headcount bands from segments 1-2 of the ICP definition.
ICP_BANDS = ("11-50", "51-100", "101-250", "251-500", "501-1000", "1001-5000")

# Categories that indicate the company builds software — which is what
# engineering capacity is sold against. Deliberately excludes broad tags:
# "Internet" and "Marketplace" match nearly every funded startup, and
# hardware or robotics need a different pitch than managed software teams.
ICP_TECH_CATEGORIES = frozenset({
    "Information Technology", "Software", "Enterprise Software", "SaaS",
    "Artificial Intelligence (AI)", "Machine Learning", "Analytics",
    "Big Data", "Data Integration", "Cloud Computing", "Cyber Security",
    "Developer APIs", "Developer Tools", "DevOps", "Information Services",
    "Internet of Things", "Apps", "Mobile Apps", "Web Development", "FinTech",
})

# Cycled so an imported list does not read as one row repeated.
TITLES = (
    "VP Engineering",
    "Chief Technology Officer",
    "Head of Engineering",
    "Director of Engineering",
    "Co-Founder and CTO",
)


def is_tech(record: dict) -> bool:
    cats = {c.strip() for c in (record.get("category_list") or "").split(",")}
    return bool(cats & ICP_TECH_CATEGORIES)


def dataset_available() -> bool:
    """False when the dataset was not shipped — the caller should hide the
    import rather than fail on click."""
    return DATASET.is_file()


def matching_companies(limit: int = 0) -> list[dict]:
    """Companies in the dataset worth contacting, most recently funded first.

    Relaxes nothing: a company must have funding data, sit in an ICP headcount
    band, and build software. Returns [] when the dataset is absent.
    """
    if not dataset_available():
        return []
    records = json.loads(DATASET.read_text())
    funded = [r for r in records if r.get("last_funding_at")]
    in_band = [r for r in funded if r.get("num_employees_enum") in ICP_BANDS]
    matches = [r for r in in_band if is_tech(r)]
    matches.sort(key=lambda r: r.get("last_funding_at", ""), reverse=True)
    return matches[:limit] if limit else matches


def _mail_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower()) or "company"


def signals_for(record: dict) -> dict:
    """Only what the dataset actually asserts. Enrichment fills the rest in
    later, and an absent signal stays absent rather than becoming a false
    negative the composer might treat as a fact."""
    signals: dict = {}
    if record.get("last_funding_at"):
        signals["signal_1_funding_event"] = {
            "present": True,
            "confidence": "high",
            "source": "crunchbase_odm",
            "last_funding_at": record["last_funding_at"],
            **({"amount_usd": record["funding_total_usd"]}
               if record.get("funding_total_usd") else {}),
        }
    firmographics = {
        k: record[k]
        for k in ("num_employees_enum", "category_list", "country_code")
        if record.get(k)
    }
    if firmographics:
        signals["firmographics"] = {
            "present": True, "confidence": "high",
            "source": "crunchbase_odm", **firmographics,
        }
    return signals


def prospect_rows(limit: int = 0) -> list[dict]:
    """Importable rows: the same shape the CSV importer accepts."""
    rows = []
    for i, record in enumerate(matching_companies(limit)):
        company = record.get("name") or "Unknown"
        rows.append({
            "email": f"demo.contact@{_mail_slug(company)}.example",
            "name": "Demo Contact (synthetic)",
            "company": company,
            "title": TITLES[i % len(TITLES)],
            "signals": signals_for(record),
        })
    return rows

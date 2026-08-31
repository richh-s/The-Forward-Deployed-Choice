"""The demo prospect must match the ICP the playbook pitches against.

The ICP is B2B *tech* ("managed talent outsourcing and project consulting to
B2B tech companies"), but "Health Care" is the most common category among
funded companies in the ICP headcount bands. A headcount-only filter therefore
picks a clinic, the composer is asked to sell engineering capacity to a
hospital, and the judge correctly penalises the result — quietly costing a
regenerate cycle on every run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed_demo_workspace import (  # noqa: E402
    ICP_BANDS,
    ICP_TECH_CATEGORIES,
    _is_tech,
    pick_demo_company,
)


def test_demo_company_is_in_an_icp_headcount_band():
    assert pick_demo_company().get("num_employees_enum") in ICP_BANDS


def test_demo_company_is_a_software_company():
    company = pick_demo_company()
    assert _is_tech(company), (
        f"{company.get('name')!r} is {company.get('category_list')!r} — the "
        "playbook pitches engineering capacity at B2B tech companies"
    )


def test_demo_company_is_not_healthcare():
    """The specific regression: a clinic selected for a B2B-tech pitch."""
    cats = {c.strip() for c in (pick_demo_company().get("category_list") or "").split(",")}
    assert not (cats & {"Health Care", "Medical", "Hospital", "Biotechnology"})


def test_selection_is_deterministic():
    """Seeding twice must produce the same prospect, or demos drift."""
    assert pick_demo_company()["name"] == pick_demo_company()["name"]


def test_icp_categories_exclude_ambiguous_tags():
    """`Internet` and `Marketplace` match nearly every funded startup; letting
    them in reintroduces non-engineering buyers."""
    assert "Internet" not in ICP_TECH_CATEGORIES
    assert "Marketplace" not in ICP_TECH_CATEGORIES


def test_is_tech_handles_missing_categories():
    assert _is_tech({}) is False
    assert _is_tech({"category_list": None}) is False
    assert _is_tech({"category_list": ""}) is False
    assert _is_tech({"category_list": "Software"}) is True
    assert _is_tech({"category_list": " Health Care , Software "}) is True

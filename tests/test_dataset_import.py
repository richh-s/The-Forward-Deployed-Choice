"""Importing prospects from the bundled dataset.

The dataset ships with the product, so the operator should not have to export
a CSV and upload it to use data the system can already read. These lock the
two properties that matter: the filter is the ICP, and no imported contact can
ever reach a real person.
"""
import httpx

from engine.db import db_session
from engine.models import Prospect
from engine.services.dataset import (
    ICP_BANDS,
    dataset_available,
    is_tech,
    matching_companies,
    prospect_rows,
)
from tests.conftest import login, post, seed_workspace


def test_dataset_ships_with_the_product():
    assert dataset_available(), "the in-app import depends on this file"


def test_every_match_is_in_the_icp():
    for c in matching_companies():
        assert c.get("last_funding_at"), f"{c.get('name')} has no funding data"
        assert c["num_employees_enum"] in ICP_BANDS
        assert is_tech(c), f"{c.get('name')} is not a software company"


def test_matches_are_a_small_fraction_of_the_dataset():
    """The point of the filter is that it rejects most of the file."""
    import json

    from engine.services.dataset import DATASET
    total = len(json.loads(DATASET.read_text()))
    assert 0 < len(matching_companies()) < total * 0.1


def test_no_imported_contact_can_ever_be_delivered_to():
    """A live send must not be able to reach a real inbox: every generated
    address sits on the reserved .example TLD."""
    for row in prospect_rows():
        assert row["email"].endswith(".example")
        assert "synthetic" in row["name"].lower()


def test_rows_only_claim_what_the_dataset_asserts():
    for row in prospect_rows(5):
        funding = row["signals"].get("signal_1_funding_event")
        if funding:
            assert funding["present"] is True
            assert funding["source"] == "crunchbase_odm"
            assert funding.get("last_funding_at")


def test_ordering_is_most_recently_funded_first():
    dates = [c["last_funding_at"] for c in matching_companies()]
    assert dates == sorted(dates, reverse=True)


# ── through the endpoint ─────────────────────────────────────────────


async def test_import_creates_prospects(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    before = len(prospect_rows())
    resp = await post(client, f"/campaigns/{seed['campaign_id']}/import-dataset")
    assert resp.status_code == 303
    async with db_session() as db:
        from sqlalchemy import select
        rows = list((await db.execute(select(Prospect).where(
            Prospect.email.like("%.example")))).scalars().all())
    assert len(rows) == before
    assert all(p.campaign_id == seed["campaign_id"] for p in rows)


async def test_reimport_is_idempotent(client: httpx.AsyncClient):
    """Clicking twice must not duplicate anyone."""
    seed = await seed_workspace()
    await login(client, seed["email"])
    await post(client, f"/campaigns/{seed['campaign_id']}/import-dataset")
    await post(client, f"/campaigns/{seed['campaign_id']}/import-dataset")
    async with db_session() as db:
        from sqlalchemy import func, select
        n = (await db.execute(select(func.count()).select_from(Prospect).where(
            Prospect.email.like("%.example")))).scalar()
    assert n == len(prospect_rows())


async def test_import_respects_a_limit(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    await post(client, f"/campaigns/{seed['campaign_id']}/import-dataset",
               {"limit": "3"})
    async with db_session() as db:
        from sqlalchemy import func, select
        n = (await db.execute(select(func.count()).select_from(Prospect).where(
            Prospect.email.like("%.example")))).scalar()
    assert n == 3

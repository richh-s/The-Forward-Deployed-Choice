"""Production-hardening regressions: synthetic signals can never reach
assertion mode, tenant URLs can't aim at private hosts (SSRF), queue lag is
visible from the web tier, list pages paginate, CSV dedup stays bounded."""
import io
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from engine.db import db_session
from engine.models import Prospect, Workspace
from engine.queue import enqueue, process_one
from engine.services.credentials import (
    CredentialValidationError,
    set_credentials,
    validate_credential_payload,
)
from tests.conftest import csrf_for, login, seed_workspace
from tests.test_challenge_compliance import GAP_SIGNALS, _capture_compose

# ── synthetic signals are quarantined into inquiry mode ──────────────


async def test_enrichment_service_synthetic_flag_is_a_tripwire():
    """The flag is computed, not asserted: False when every signal is a real
    lookup or an honest not-checked entry; True the moment any mock/proxy
    source appears (the engine then forces inquiry mode)."""
    from enrichment.live_sources import has_fabricated_sources
    from enrichment.service import app as enrichment_app

    transport = httpx.ASGITransport(app=enrichment_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://enrich"
    ) as client:
        resp = await client.post("/enrich", json={
            "email": "jordan@novapay.example",
            "company": "NovaPay Technologies",
        })
    assert resp.status_code == 200
    body = resp.json()
    # Live lookups are disabled in tests; every signal must be real data or
    # explicitly not-checked — nothing fabricated, so the flag is False...
    assert body["synthetic"] is False
    for sig in body["signals"].values():
        if isinstance(sig, dict):
            src = str(sig.get("source", ""))
            assert "mock" not in src and "proxy" not in src
    # ...and the tripwire still fires on any fabricated value.
    assert has_fabricated_sources(
        {"x": {"source": "linkedin_fallback_mock"}}
    ) is True


async def test_synthetic_source_marks_prospect_signals():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "enrichment",
            {"url": "https://signals.example.com/enrich"},
        )
        await enqueue(db, "enrich_prospect", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
        })
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.stage = "new"
    body = {"signals": GAP_SIGNALS, "icp_segment": 2, "synthetic": True}
    with patch(
        "engine.services.enrichment.fetch_signals",
        new=AsyncMock(return_value=body),
    ):
        assert await process_one()
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.signals["_synthetic"] is True
        assert "competitor_gap" in prospect.signals


async def test_synthetic_signals_force_inquiry_mode():
    """High-confidence signals from a synthetic source must compose in
    inquiry mode with the research-finding opener suppressed."""
    from engine.services.compose import compose_outreach

    seed = await seed_workspace()
    captured, patcher = _capture_compose()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.signals = {**GAP_SIGNALS, "_synthetic": True}
        with patcher:
            await compose_outreach(db, ws, prospect, None)
    assert "Mode: INQUIRY" in captured["user"]
    assert "SYNTHETIC" in captured["user"]
    assert "RESEARCH FINDING" not in captured["user"]


async def test_unflagged_high_confidence_signals_still_assert():
    from engine.services.compose import compose_outreach

    seed = await seed_workspace()
    captured, patcher = _capture_compose()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.signals = json.loads(json.dumps(GAP_SIGNALS))
        with patcher:
            await compose_outreach(db, ws, prospect, None)
    assert "Mode: ASSERTION" in captured["user"]
    assert "RESEARCH FINDING" in captured["user"]


# ── tenant-configured URLs can't point at private hosts ──────────────


@pytest.mark.parametrize("url", [
    "https://10.0.0.1/enrich",
    "https://192.168.1.5/enrich",
    "https://169.254.169.254/latest/meta-data/",
    "https://[fd00::1]/enrich",
])
def test_private_hosts_rejected(url):
    with pytest.raises(CredentialValidationError):
        validate_credential_payload("enrichment", {"url": url})


def test_public_and_unresolvable_hosts_allowed():
    # Unresolvable hostnames pass validation (the request itself will
    # fail) — validation must not depend on DNS being reachable.
    payload = validate_credential_payload(
        "enrichment", {"url": "https://signals.test.invalid/enrich"}
    )
    assert payload["url"].startswith("https://")


def test_loopback_still_allowed_in_development():
    payload = validate_credential_payload(
        "enrichment", {"url": "http://localhost:8100/enrich"}
    )
    assert payload["url"] == "http://localhost:8100/enrich"


# ── queue lag visible from the web tier ──────────────────────────────


async def test_metrics_expose_queue_lag(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await enqueue(db, "compose_draft", {
            "workspace_id": seed["workspace_id"],
            "prospect_id": seed["prospect_id"],
        })
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "engine_jobs_runnable 1" in body
    assert "engine_jobs_oldest_runnable_age_seconds" in body


# ── pagination ───────────────────────────────────────────────────────


async def test_prospects_page_paginates(client: httpx.AsyncClient, monkeypatch):
    from engine.routes import dashboard

    monkeypatch.setattr(dashboard, "PROSPECTS_PAGE_SIZE", 1)
    seed = await seed_workspace()
    async with db_session() as db:
        db.add(Prospect(
            workspace_id=seed["workspace_id"],
            campaign_id=seed["campaign_id"],
            email="second@x.test",
            name="Second Prospect",
        ))
    await login(client, seed["email"])
    page1 = await client.get("/prospects")
    assert page1.status_code == 200
    assert "Page 1 of 2" in page1.text
    page2 = await client.get("/prospects?page=2")
    assert page2.status_code == 200
    assert "Page 2 of 2" in page2.text
    # Both prospects reachable, one per page.
    emails_seen = {
        e for e in ("second@x.test", seed["prospect_email"])
        if e in page1.text or e in page2.text
    }
    assert emails_seen == {"second@x.test", seed["prospect_email"]}
    assert not ("second@x.test" in page1.text and "second@x.test" in page2.text)


# ── CSV dedup stays correct (and bounded) ────────────────────────────


async def test_csv_in_file_duplicates_skipped(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    csv_content = (
        "email,name\n"
        "dup@x.test,First\n"
        "dup@x.test,Second\n"
    )
    resp = await client.post(
        f"/campaigns/{seed['campaign_id']}/upload",
        data={"csrf_token": csrf_for(client)},
        files={"file": ("p.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 303
    assert "Imported+1" in resp.headers["location"]
    assert "1+duplicates" in resp.headers["location"]

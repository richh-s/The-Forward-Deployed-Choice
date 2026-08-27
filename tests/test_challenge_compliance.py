"""Challenge-spec compliance: the mandated data sources flow through the
product — enrichment service contract, ICP segment wiring, research-finding
composition, HubSpot lead provenance and conversation logging."""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from engine.db import db_session
from engine.models import Draft, Job, Prospect, Workspace
from engine.queue import enqueue, process_one
from engine.services.credentials import (
    CredentialValidationError,
    set_credentials,
    validate_credential_payload,
)
from engine.services.llm import LLMResult
from tests.conftest import seed_workspace

GAP_SIGNALS = {
    "signal_1_funding_event": {
        "present": True, "confidence": "high", "amount_usd": 16000000,
        "crunchbase_id": "cb-uuid-123",
    },
    "signal_5_ai_maturity": {"score": 1, "confidence": "medium"},
    "competitor_gap": {
        "confidence": "medium",
        "distribution_position": {
            "prospect_score": 1, "sector_median": 2,
            "prospect_percentile": 20, "peer_count": 7,
        },
        "gap_findings": [{
            "practice": "Dedicated MLOps engineering capability",
            "prospect_state": "No public MLOps roles found.",
            "confidence": "medium",
        }],
    },
}


# ── enrichment service (challenge pipeline behind the product contract) ──


async def test_enrichment_service_returns_contract_shape():
    import sys as _sys

    from enrichment.service import app as enrichment_app

    # Data-driven: the same deterministic pick the demo seed uses — a REAL
    # funded company from the handed ODM sample, nothing hand-written.
    _sys.path.insert(0, "scripts")
    from seed_demo_workspace import pick_demo_company

    company = pick_demo_company()
    transport = httpx.ASGITransport(app=enrichment_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://enrich"
    ) as client:
        resp = await client.post("/enrich", json={
            "email": "demo@example.example",
            "company": company["name"],
        })
    assert resp.status_code == 200
    body = resp.json()
    signals = body["signals"]
    # The six hiring-signal-brief signals plus the competitor gap.
    for key in (
        "signal_1_funding_event", "signal_2_job_post_velocity",
        "signal_3_layoff_event", "signal_4_leadership_change",
        "signal_5_ai_maturity", "signal_6_icp_segment", "competitor_gap",
    ):
        assert key in signals, key
    # A funded ODM record carries its Crunchbase reference.
    assert body["crunchbase_id"] == company["uuid"]
    gap = signals["competitor_gap"]
    assert gap["distribution_position"]["peer_count"] > 0
    assert isinstance(body.get("icp_segment"), (int, type(None)))


async def test_enrichment_service_enforces_api_key(monkeypatch):
    from enrichment.service import app as enrichment_app

    monkeypatch.setenv("ENRICHMENT_API_KEY", "sekret-key-123")
    transport = httpx.ASGITransport(app=enrichment_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://enrich"
    ) as client:
        denied = await client.post("/enrich", json={"company": "NovaPay Technologies"})
        assert denied.status_code == 401
        allowed = await client.post(
            "/enrich", json={"company": "NovaPay Technologies"},
            headers={"Authorization": "Bearer sekret-key-123"},
        )
        assert allowed.status_code == 200


# ── engine: ICP segment + signals land on the prospect ───────────────


async def test_enrich_prospect_sets_icp_segment():
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
    body = {"signals": GAP_SIGNALS, "icp_segment": 2}
    with patch(
        "engine.services.enrichment.fetch_signals",
        new=AsyncMock(return_value=body),
    ):
        assert await process_one()
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        assert prospect.stage == "enriched"
        assert prospect.icp_segment == 2
        assert prospect.signals["competitor_gap"]["confidence"] == "medium"


async def test_localhost_http_enrichment_url_allowed():
    payload = validate_credential_payload(
        "enrichment", {"url": "http://localhost:8100/enrich"}
    )
    assert payload["url"].startswith("http://localhost")
    with pytest.raises(CredentialValidationError):
        validate_credential_payload("enrichment", {"url": "http://evil.internal/x"})


# ── composer: leads with the research finding, confidence-gated ──────


def _capture_compose():
    captured = {}

    async def fake_complete(db, workspace_id, **kwargs):
        captured["system"] = kwargs.get("system", "")
        captured["user"] = kwargs["messages"][0]["content"]
        return LLMResult(
            text=json.dumps({
                "subject": "s", "body": "b", "mode_used": "inquiry",
                "grounding_notes": "n",
            }),
            model="claude-opus-5", input_tokens=10, output_tokens=10,
        )

    return captured, patch(
        "engine.services.llm.complete", new=AsyncMock(side_effect=fake_complete)
    )


async def test_compose_leads_with_research_finding():
    from engine.services.compose import compose_outreach

    seed = await seed_workspace()
    captured, patcher = _capture_compose()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.signals = GAP_SIGNALS
        with patcher:
            await compose_outreach(db, ws, prospect, None)
    assert "RESEARCH FINDING" in captured["user"]
    assert "Dedicated MLOps engineering capability" in captured["user"]
    assert "never condescending" in captured["user"]


async def test_low_confidence_gap_is_not_mentioned():
    from engine.services.compose import compose_outreach

    seed = await seed_workspace()
    low = json.loads(json.dumps(GAP_SIGNALS))
    low["competitor_gap"]["confidence"] = "low"
    captured, patcher = _capture_compose()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.signals = low
        with patcher:
            await compose_outreach(db, ws, prospect, None)
    assert "RESEARCH FINDING" not in captured["user"]
    assert "do \nNOT mention competitors" in captured["user"] or \
        "NOT mention competitors" in captured["user"]


async def test_case_studies_reach_the_system_prompt():
    from engine.services.compose import build_system_prompt

    seed = await seed_workspace()
    async with db_session() as db:
        ws = await db.get(Workspace, seed["workspace_id"])
        ws.playbook = {
            **ws.playbook,
            "case_studies": "Fintech scale-up: 40% cost reduction in 9 months.",
        }
        prompt = build_system_prompt(ws, None)
    assert "CASE STUDIES" in prompt
    assert "40% cost reduction" in prompt
    assert "NEVER invent additional" in prompt


# ── HubSpot: lead provenance + conversation events ───────────────────


async def test_hubspot_properties_carry_enrichment_provenance():
    from engine.services.hubspot import _enrichment_properties

    seed = await seed_workspace()
    async with db_session() as db:
        prospect = await db.get(Prospect, seed["prospect_id"])
        prospect.signals = GAP_SIGNALS
        prospect.icp_segment = 1
        props = _enrichment_properties(prospect)
    assert props["crunchbase_id"] == "cb-uuid-123"
    assert props["icp_segment"] == "1"
    assert props["ai_maturity_score"] == "1"
    assert props["funding_amount_usd"] == "16000000"
    assert props["enrichment_timestamp"]
    assert props["signal_source"] == "conversion-engine"


async def test_sends_enqueue_hubspot_conversation_log():
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend", {"api_key": "re_test"}
        )
        db.add(Draft(
            workspace_id=seed["workspace_id"], prospect_id=seed["prospect_id"],
            subject="Hi", body="Body", status="approved",
        ))
        await db.flush()
        draft_id = (await db.execute(select(Draft.id))).scalar_one()
        await enqueue(db, "send_draft", {"draft_id": draft_id},
                      idempotency_key=f"send_draft:{draft_id}")
    with patch(
        "engine.services.emailer._resend_send",
        new=AsyncMock(return_value={"id": "re_hs"}),
    ):
        assert await process_one()
    async with db_session() as db:
        note_job = (await db.execute(
            select(Job).where(Job.type == "hubspot_log_event")
        )).scalar_one()
        assert note_job.idempotency_key.startswith("hs_note:")
    # Without HubSpot credentials the handler is a clean no-op.
    while await process_one():
        pass
    async with db_session() as db:
        note_job = (await db.execute(
            select(Job).where(Job.type == "hubspot_log_event")
        )).scalar_one()
        assert note_job.status == "done"


# ── market-space stretch outputs exist and are fresh-buildable ───────


def test_market_space_outputs_build():
    import subprocess
    import sys
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/build_market_space.py"],
        cwd=base, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (base / "market_space.csv").exists()
    assert (base / "top_cells.md").exists()
    header = (base / "market_space.csv").read_text().splitlines()[0]
    assert header.startswith("sector,size_band,ai_readiness_band,population")

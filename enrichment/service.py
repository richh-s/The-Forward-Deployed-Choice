"""HTTP wrapper exposing the challenge enrichment pipeline as the product's
per-workspace enrichment source.

This is the bridge between the Week-10 research pipeline (Crunchbase ODM +
layoffs.fyi + job-post velocity + AI-maturity scoring + ICP classification +
competitor gap brief) and the engine's enrichment contract:

    POST /enrich          Authorization: Bearer $ENRICHMENT_API_KEY (if set)
    body: {"email", "name", "company", "title", "phone"}
    200 → {"signals": {...}, "icp_segment": 1-4 | null}

Run it next to the engine and point Settings → credentials → enrichment at it:

    ENRICHMENT_API_KEY=<random> uvicorn enrichment.service:app --port 8100

The response's `signals` object is exactly what lands on `Prospect.signals`:
signals 1–6 from the hiring-signal brief plus a condensed `competitor_gap`
entry the composer uses to lead outreach with a research finding. Playwright
(job-post velocity) is optional — without it that one signal degrades to its
low-confidence fallback.
"""
import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from enrichment.pipeline import enrich_company, generate_competitor_gap_brief

logger = logging.getLogger(__name__)

app = FastAPI(title="Tenacious Enrichment Service", docs_url=None, redoc_url=None)


class ProspectIn(BaseModel):
    email: str = ""
    name: str = ""
    company: str = ""
    title: str = ""
    phone: str = ""


def _check_auth(authorization: str | None) -> None:
    key = os.environ.get("ENRICHMENT_API_KEY", "")
    if not key:
        return  # open mode — for local/tailnet use only
    presented = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(key, presented):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _condense_gap(gap: dict) -> dict:
    """The full brief is large (per-peer justifications); embed only what the
    composer and judge need to ground a research-finding opener."""
    findings = [
        {
            "practice": f.get("practice", ""),
            "prospect_state": f.get("prospect_state", ""),
            "confidence": f.get("confidence", "low"),
            "peer_evidence": (f.get("peer_evidence") or [])[:1],
        }
        for f in (gap.get("gap_findings") or [])[:3]
    ]
    return {
        "sector": gap.get("prospect_sector", ""),
        "prospect_ai_maturity_score": gap.get("prospect_ai_maturity_score"),
        "distribution_position": gap.get("distribution_position", {}),
        "gap_findings": findings,
        "suggested_pitch_shift": gap.get("suggested_pitch_shift", ""),
        "sparse_sector": gap.get("sparse_sector", False),
        "sparse_sector_note": gap.get("sparse_sector_note", ""),
        "confidence": max(
            (f["confidence"] for f in findings),
            key=lambda c: {"low": 0, "medium": 1, "high": 2}.get(c, 0),
            default="low",
        ),
        "source": "competitor_gap_brief",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "enrichment"}


@app.post("/enrich")
def enrich(prospect: ProspectIn, authorization: str | None = Header(default=None)):
    """Sync endpoint on purpose: FastAPI runs it in a threadpool, and the
    pipeline (Playwright, file reads) is synchronous."""
    _check_auth(authorization)
    company = prospect.company.strip() or prospect.email.split("@")[-1].split(".")[0]
    if not company:
        raise HTTPException(status_code=422, detail="company or email required")

    result = enrich_company(company)
    signals = result.get("signals", {})

    ai_score = int((signals.get("signal_5_ai_maturity") or {}).get("score", 0))
    sector = (
        (result.get("firmographics") or {}).get("industry", "")
        or (signals.get("signal_1_funding_event", {}).get("firmographics") or {})
        .get("industry", "")
    ).split(",")[0].strip() or "default"
    domain = prospect.email.split("@")[-1] if "@" in prospect.email else ""
    gap = generate_competitor_gap_brief(company, domain, ai_score, sector=sector)
    signals["competitor_gap"] = _condense_gap(gap)

    icp = signals.get("signal_6_icp_segment") or {}
    segment = icp.get("segment_number")
    logger.info(
        "Enriched %s: ai=%d segment=%s", company, ai_score, segment or "abstain"
    )
    return {
        "signals": signals,
        "icp_segment": int(segment) if isinstance(segment, int) else None,
        "crunchbase_id": (signals.get("signal_1_funding_event") or {}).get(
            "crunchbase_id", ""
        ),
        # This pipeline derives several AI-maturity sub-signals and the
        # competitor peer set from deterministic proxies, not live lookups
        # (see enrichment/pipeline.py). The engine must never let these
        # reach assertion mode: the flag forces inquiry-mode composition.
        "synthetic": True,
    }

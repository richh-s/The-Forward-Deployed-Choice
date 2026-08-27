"""The /api/v1 JSON layer that backs the Next.js dashboard."""
import httpx

from engine.db import db_session
from engine.models import Prospect
from tests.conftest import login, seed_workspace


async def test_me_requires_auth(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401


async def test_prelogin_sets_cookie_and_returns_token(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/prelogin")
    assert resp.status_code == 200
    assert resp.json()["csrf_token"]
    assert "csrft" in resp.cookies


async def test_me_returns_workspace_and_csrf(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    me = (await client.get("/api/v1/me")).json()
    assert me["user"]["email"] == seed["email"]
    assert me["workspace"]["slug"] == seed["slug"]
    assert me["csrf_token"]
    assert isinstance(me["stages"], list)


async def test_csrf_token_from_me_works_on_form_routes(
    client: httpx.AsyncClient,
):
    """The SPA's whole write path: token from /me + FormData to a form route."""
    seed = await seed_workspace()
    await login(client, seed["email"])
    me = (await client.get("/api/v1/me")).json()
    resp = await client.post(
        "/campaigns",
        data={"csrf_token": me["csrf_token"], "name": "SPA campaign"},
    )
    assert resp.status_code == 303
    assert "Campaign+created" in resp.headers["location"]


async def test_summary_and_lists(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    summary = (await client.get("/api/v1/summary")).json()
    assert summary["stage_counts"].get("enriched") == 1
    assert "metrics" in summary

    campaigns = (await client.get("/api/v1/campaigns")).json()["campaigns"]
    assert campaigns[0]["prospect_count"] == 1

    prospects = (await client.get("/api/v1/prospects?q=Jane")).json()
    assert prospects["pager"]["total"] == 1
    pid = prospects["prospects"][0]["id"]

    detail = (await client.get(f"/api/v1/prospects/{pid}")).json()
    assert detail["prospect"]["email"] == seed["prospect_email"]

    for path in ("/api/v1/approvals", "/api/v1/jobs", "/api/v1/analytics",
                 "/api/v1/settings"):
        assert (await client.get(path)).status_code == 200


async def test_tenancy_isolation_on_json_api(client: httpx.AsyncClient):
    seed_a = await seed_workspace(slug="alpha", admin_email="a@alpha.test")
    seed_b = await seed_workspace(slug="beta", admin_email="b@beta.test")
    await login(client, seed_b["email"])
    # Workspace B must not read workspace A's prospect.
    resp = await client.get(f"/api/v1/prospects/{seed_a['prospect_id']}")
    assert resp.status_code == 404
    listing = (await client.get("/api/v1/prospects")).json()
    emails = {p["email"] for p in listing["prospects"]}
    assert seed_a["prospect_email"] not in emails
    async with db_session() as db:
        assert await db.get(Prospect, seed_a["prospect_id"]) is not None

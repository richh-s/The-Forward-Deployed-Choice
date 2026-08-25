"""Auth: first-run setup, login/logout, tenancy isolation, role checks."""
import httpx

from tests.conftest import login, seed_workspace


async def test_setup_creates_workspace_and_admin(client: httpx.AsyncClient):
    resp = await client.post(
        "/setup",
        data={
            "workspace_name": "Boingo AI",
            "admin_name": "Aman",
            "email": "admin@boingo.test",
            "password": "a-long-password",
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/settings")
    # Setup is one-shot: second attempt bounces to login.
    resp = await client.post(
        "/setup",
        data={
            "workspace_name": "Evil", "email": "evil@x.test",
            "password": "another-long-pass",
        },
    )
    assert resp.headers["location"] == "/login"


async def test_login_bad_credentials(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.post(
        "/login", data={"email": "admin@acme.test", "password": "wrong"}
    )
    assert "error" in resp.headers["location"]


async def test_protected_page_redirects_browser(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_protected_api_returns_401(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.get("/")
    assert resp.status_code == 401


async def test_login_and_view_dashboard(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Pipeline" in resp.text


async def test_tenancy_isolation(client: httpx.AsyncClient):
    seed_a = await seed_workspace(slug="alpha", admin_email="a@alpha.test")
    seed_b = await seed_workspace(slug="beta", admin_email="b@beta.test")
    await login(client, seed_b["email"])
    # B cannot see A's campaign or prospect.
    assert (await client.get(f"/campaigns/{seed_a['campaign_id']}")).status_code == 404
    assert (await client.get(f"/prospects/{seed_a['prospect_id']}")).status_code == 404
    # And cannot mutate them.
    resp = await client.post(
        f"/prospects/{seed_a['prospect_id']}/stage", data={"stage": "lost"}
    )
    assert resp.status_code == 404


async def test_operator_cannot_touch_admin_settings(client: httpx.AsyncClient):
    from engine.db import db_session
    from engine.models import User
    from engine.security import hash_password

    seed = await seed_workspace()
    async with db_session() as db:
        db.add(User(
            workspace_id=seed["workspace_id"],
            email="op@acme.test",
            password_hash=hash_password("correct-horse-battery"),
            role="operator",
        ))
    await login(client, "op@acme.test")
    resp = await client.post("/settings/workspace", data={"name": "Hacked"})
    assert resp.status_code == 403

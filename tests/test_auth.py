"""Auth: first-run setup, login/logout, tenancy isolation, role checks,
CSRF enforcement, and login rate limiting."""
import httpx

from tests.conftest import login, post, prelogin_csrf, seed_workspace


async def test_setup_creates_workspace_and_admin(client: httpx.AsyncClient):
    token = await prelogin_csrf(client, "/setup")
    resp = await client.post(
        "/setup",
        data={
            "workspace_name": "Boingo AI",
            "admin_name": "Aman",
            "email": "admin@boingo.test",
            "password": "a-long-password",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/settings")
    # Setup is one-shot: second attempt bounces to login.
    resp = await post(
        client, "/setup",
        data={
            "workspace_name": "Evil", "email": "evil@x.test",
            "password": "another-long-pass",
        },
    )
    assert resp.headers["location"] == "/login"


async def test_login_bad_credentials(client: httpx.AsyncClient):
    await seed_workspace()
    token = await prelogin_csrf(client, "/login")
    resp = await client.post(
        "/login",
        data={"email": "admin@acme.test", "password": "wrong",
              "csrf_token": token},
    )
    assert "error" in resp.headers["location"]


async def test_login_rate_limited(client: httpx.AsyncClient):
    await seed_workspace()
    token = await prelogin_csrf(client, "/login")
    statuses = []
    for _ in range(6):
        resp = await client.post(
            "/login",
            data={"email": "admin@acme.test", "password": "wrong",
                  "csrf_token": token},
        )
        statuses.append(resp.status_code)
    assert statuses[-1] == 429  # 5 attempts allowed, the 6th throttled


async def test_post_without_csrf_rejected(client: httpx.AsyncClient):
    seed = await seed_workspace()
    await login(client, seed["email"])
    resp = await client.post("/campaigns", data={"name": "No token"})
    assert resp.status_code == 403
    resp = await client.post(
        "/campaigns", data={"name": "Bad token", "csrf_token": "forged"}
    )
    assert resp.status_code == 403


async def test_security_headers_present(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.get("/login")
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in resp.headers
    assert "x-request-id" in resp.headers


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
    resp = await post(
        client, f"/prospects/{seed_a['prospect_id']}/stage", data={"stage": "lost"}
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
    resp = await post(client, "/settings/workspace", data={"name": "Hacked"})
    assert resp.status_code == 403

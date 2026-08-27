"""Test fixtures.

Environment is pinned BEFORE any engine import so cached settings pick up the
test database and safety rails (sink mode, worker off).
"""
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="engine-tests-")
os.environ.update(
    {
        # TEST_DATABASE_URL lets CI point the suite at real Postgres.
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_TMPDIR}/test.db"
        ),
        "ENVIRONMENT": "development",
        "APP_SECRET_KEY": "test-secret-key-not-for-production",
        "LIVE_MODE": "false",
        "SINK_EMAIL": "sink@example.com",
        "SINK_PHONE": "+15550000000",
        "RUN_WORKER": "false",
        "ANTHROPIC_API_KEY": "test-key-unused",
        "BASE_URL": "http://testserver",
        # Enrichment live lookups (job boards, GitHub) are real network
        # calls — off in tests; signals honestly report "not checked".
        "ENRICHMENT_LIVE_LOOKUPS": "false",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from engine import models, ratelimit  # noqa: E402, F401
from engine.app import create_app  # noqa: E402
from engine.db import Base, db_session, dispose_engine, get_engine  # noqa: E402
from engine.models import Campaign, Prospect, User, Workspace  # noqa: E402
from engine.security import csrf_token_for, hash_password  # noqa: E402


@pytest.fixture(autouse=True)
async def fresh_db():
    """Blank schema per test."""
    ratelimit.reset_all()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


async def seed_workspace(
    *,
    slug: str = "acme",
    with_campaign: bool = True,
    admin_email: str = "admin@acme.test",
) -> dict:
    """Create a workspace + admin (+ campaign + prospect) directly in the DB."""
    async with db_session() as db:
        ws = Workspace(
            name=slug.capitalize(),
            slug=slug,
            from_email=f"outreach@{slug}.test",
            from_name=slug.capitalize(),
            playbook={
                "company_name": slug.capitalize(),
                "value_proposition": "We provide managed engineering capacity.",
                "sign_off": "Alex, Engagement Manager",
            },
        )
        db.add(ws)
        await db.flush()
        user = User(
            workspace_id=ws.id,
            email=admin_email,
            password_hash=hash_password("correct-horse-battery"),
            role="admin",
        )
        db.add(user)
        campaign = None
        prospect = None
        if with_campaign:
            campaign = Campaign(
                workspace_id=ws.id, name="Q3 outbound", status="active"
            )
            db.add(campaign)
            await db.flush()
            prospect = Prospect(
                workspace_id=ws.id,
                campaign_id=campaign.id,
                email=f"jane@prospect-{slug}.test",
                name="Jane Doe",
                company="Prospect Co",
                phone="+254700000001",
                signals={
                    "signal_1_funding_event": {
                        "confidence": "high", "amount_usd": 12000000
                    },
                    "signal_2_job_post_velocity": {"confidence": "high"},
                },
                stage="enriched",
            )
            db.add(prospect)
        await db.flush()
        return {
            "workspace_id": ws.id,
            "slug": slug,
            "user_id": user.id,
            "email": admin_email,
            "campaign_id": campaign.id if campaign else None,
            "prospect_id": prospect.id if prospect else None,
            "prospect_email": prospect.email if prospect else None,
        }


def csrf_for(client: httpx.AsyncClient) -> str:
    """CSRF token for the client's current session cookie."""
    session_token = client.cookies.get("engine_session")
    return csrf_token_for(session_token) if session_token else ""


async def post(client: httpx.AsyncClient, url: str, data: dict | None = None, **kw):
    """client.post with the CSRF token the dashboard forms would carry."""
    data = dict(data or {})
    data.setdefault("csrf_token", csrf_for(client))
    return await client.post(url, data=data, **kw)


async def prelogin_csrf(client: httpx.AsyncClient, page: str) -> str:
    """GET a pre-login page (/login, /setup) to obtain its double-submit
    CSRF cookie; returns the token to send in the form."""
    await client.get(page)
    return client.cookies.get("csrft", "")


async def login(
    client: httpx.AsyncClient, email: str, password: str = "correct-horse-battery"
) -> None:
    token = await prelogin_csrf(client, "/login")
    resp = await client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/", resp.text

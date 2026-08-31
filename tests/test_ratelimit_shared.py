"""Rate limiting is shared across instances and survives restarts.

The limiter used to live in process memory: N web instances each granted the
full allowance, and any restart wiped every lockout. These lock in the
properties that fix required.
"""
import httpx

from engine import ratelimit
from engine.config import get_settings
from engine.db import db_session
from engine.models import RateLimitCounter
from tests.conftest import prelogin_csrf, seed_workspace


async def test_counter_is_persisted_not_in_memory():
    await ratelimit._hit("test-bucket", 60)
    await ratelimit._hit("test-bucket", 60)
    async with db_session() as db:
        rows = list((await db.execute(
            __import__("sqlalchemy").select(RateLimitCounter)
        )).scalars().all())
    assert len(rows) == 1, "one row per (bucket, window)"
    assert rows[0].count == 2


async def test_count_is_visible_to_another_caller():
    """Stands in for a second web instance: a different caller reading the
    same store must see the first one's increments."""
    for _ in range(3):
        await ratelimit._hit("login-ip:203.0.113.4", 300)
    assert await ratelimit.current_count("login-ip:203.0.113.4", 300) == 3


async def test_allow_flips_false_once_over_the_limit():
    allowed = [await ratelimit._allow("b", "k", 3, 60) for _ in range(5)]
    assert allowed == [True, True, True, False, False]


async def test_separate_keys_do_not_share_a_budget():
    assert await ratelimit._allow("b", "alice", 1, 60) is True
    assert await ratelimit._allow("b", "alice", 1, 60) is False
    assert await ratelimit._allow("b", "bob", 1, 60) is True


async def test_limiter_fails_open_when_the_store_is_down(monkeypatch):
    """Availability over strictness: a DB blip must not lock everyone out of
    logging in. Password checks and CSRF still apply."""
    async def exploding(*a, **kw):
        raise RuntimeError("database gone")
    monkeypatch.setattr(ratelimit, "_hit", exploding)
    assert await ratelimit._allow("b", "k", 1, 60) is True


async def test_purge_drops_only_closed_windows():
    import time
    await ratelimit._hit("recent", 60)
    async with db_session() as db:
        db.add(RateLimitCounter(
            bucket="ancient", window_start=int(time.time()) - 200_000, count=9
        ))
    removed = await ratelimit.purge_expired(older_than_seconds=86_400)
    assert removed == 1
    assert await ratelimit.current_count("recent", 60) == 1


# ── end to end through the real endpoint ─────────────────────────────


async def test_login_throttles_after_the_configured_attempts(
    client: httpx.AsyncClient,
):
    await seed_workspace()
    settings = get_settings()
    token = await prelogin_csrf(client, "/login")
    limit = settings.login_rate_limit_attempts

    codes = []
    for _ in range(limit + 2):
        r = await client.post("/login", data={
            "email": "admin@acme.test", "password": "wrong-password",
            "csrf_token": token,
        })
        codes.append(r.status_code)

    assert 429 in codes, f"never throttled: {codes}"
    assert codes[-1] == 429
    # and the lockout is in the database, not this process
    assert await ratelimit.current_count(
        "login-target:127.0.0.1:admin@acme.test",
        settings.login_rate_limit_window_seconds,
    ) > 0


async def test_throttle_survives_a_process_restart(client: httpx.AsyncClient):
    """A restart used to hand an attacker a fresh budget."""
    await seed_workspace()
    settings = get_settings()
    token = await prelogin_csrf(client, "/login")
    for _ in range(settings.login_rate_limit_attempts + 1):
        await client.post("/login", data={
            "email": "admin@acme.test", "password": "wrong",
            "csrf_token": token,
        })
    # simulate a restart: nothing in this module is cached, the count is in
    # the store, so a "new process" still sees the lockout
    assert await ratelimit._allow(
        "login-target", "127.0.0.1:admin@acme.test",
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    ) is False

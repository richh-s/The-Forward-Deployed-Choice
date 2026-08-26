"""Webhooks fail closed: unsigned or mis-signed requests are rejected."""
import base64
import hashlib
import hmac
import json
import time

import httpx

from engine.db import db_session
from engine.services.credentials import set_credentials
from tests.conftest import seed_workspace


async def test_resend_rejected_without_secret_configured(client: httpx.AsyncClient):
    await seed_workspace()
    resp = await client.post(
        "/webhooks/acme/resend", content=b"{}",
        headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,zz"},
    )
    assert resp.status_code == 401


async def test_resend_rejected_with_bad_signature(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        secret = base64.b64encode(b"0" * 32).decode()
        await set_credentials(
            db, seed["workspace_id"], "resend",
            {"api_key": "re_x", "webhook_secret": f"whsec_{secret}"},
        )
    resp = await client.post(
        "/webhooks/acme/resend", content=b"{}",
        headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,bad"},
    )
    assert resp.status_code == 401


async def test_resend_accepts_valid_signature_and_dedups(client: httpx.AsyncClient):
    seed = await seed_workspace()
    raw_key = b"1" * 32
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend",
            {
                "api_key": "re_x",
                "webhook_secret": "whsec_" + base64.b64encode(raw_key).decode(),
            },
        )
    payload = json.dumps(
        {"type": "email.opened", "data": {"email_id": "em_1", "to": ["x@y.z"]}}
    ).encode()
    ts = str(int(time.time()))
    to_sign = f"msg_1.{ts}.".encode() + payload
    sig = base64.b64encode(
        hmac.new(raw_key, to_sign, hashlib.sha256).digest()
    ).decode()
    headers = {
        "svix-id": "msg_1",
        "svix-timestamp": ts,
        "svix-signature": f"v1,{sig}",
    }
    resp = await client.post("/webhooks/acme/resend", content=payload, headers=headers)
    assert resp.status_code == 200 and "duplicate" not in resp.json()
    # Replay is detected via the WebhookEvent ledger.
    resp = await client.post("/webhooks/acme/resend", content=payload, headers=headers)
    assert resp.json().get("duplicate") is True


async def test_resend_stale_timestamp_rejected(client: httpx.AsyncClient):
    """A correctly signed but old request is a replay — reject it."""
    seed = await seed_workspace()
    raw_key = b"1" * 32
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "resend",
            {
                "api_key": "re_x",
                "webhook_secret": "whsec_" + base64.b64encode(raw_key).decode(),
            },
        )
    payload = b"{}"
    ts = str(int(time.time()) - 3600)
    sig = base64.b64encode(
        hmac.new(raw_key, f"msg_2.{ts}.".encode() + payload, hashlib.sha256).digest()
    ).decode()
    resp = await client.post(
        "/webhooks/acme/resend", content=payload,
        headers={"svix-id": "msg_2", "svix-timestamp": ts,
                 "svix-signature": f"v1,{sig}"},
    )
    assert resp.status_code == 401


async def test_calcom_rejected_without_header(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "calcom",
            {"api_key": "k", "webhook_secret": "s3cret"},
        )
    resp = await client.post("/webhooks/acme/calcom", content=b"{}")
    assert resp.status_code == 401


async def test_sms_rejected_with_wrong_token(client: httpx.AsyncClient):
    seed = await seed_workspace()
    async with db_session() as db:
        await set_credentials(
            db, seed["workspace_id"], "africastalking",
            {"username": "sandbox", "api_key": "atsk", "webhook_token": "good"},
        )
    resp = await client.post(
        "/webhooks/acme/sms/wrong", data={"text": "hi", "from": "+254700000001"}
    )
    assert resp.status_code == 401


async def test_unknown_workspace_404(client: httpx.AsyncClient):
    resp = await client.post("/webhooks/nope/calcom", content=b"{}")
    assert resp.status_code == 404

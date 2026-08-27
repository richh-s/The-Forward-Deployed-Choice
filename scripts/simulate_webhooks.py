"""Send correctly-signed provider webhooks at a local engine — test the
inbound pipeline without real provider accounts.

The webhooks fail closed (signature-verified), so hand-rolled curl can't
exercise them. This script reads the workspace's stored credentials from the
database, signs the payload exactly as the provider would, and POSTs it.

Usage (run with the same DATABASE_URL as the server):
    python scripts/simulate_webhooks.py reply   --slug tenacious --from-email jordan.reyes@novapay.example --text "Sounds interesting — what would a 3-engineer pod cost?"
    python scripts/simulate_webhooks.py booking --slug tenacious --prospect-email jordan.reyes@novapay.example --hours-ahead 20
    python scripts/simulate_webhooks.py sms     --slug tenacious --from-phone +254700000001 --text STOP
    python scripts/simulate_webhooks.py delivery --slug tenacious --event email.bounced --to someone@example.com

reply/delivery need the workspace's `resend` credential to include a
webhook_secret (any value like: whsec_<base64 of 32 bytes> works for local
testing); booking needs a `calcom` webhook_secret; sms needs the
africastalking credential (its URL token is auto-generated on save).
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import secrets as pysecrets
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from engine.db import db_session  # noqa: E402
from engine.models import Prospect, Workspace  # noqa: E402
from engine.services.credentials import get_credentials  # noqa: E402


async def _workspace(slug: str) -> Workspace:
    async with db_session() as db:
        ws = (await db.execute(
            select(Workspace).where(Workspace.slug == slug)
        )).scalar_one_or_none()
        if ws is None:
            raise SystemExit(f"No workspace with slug {slug!r}")
        return ws


async def _creds(workspace_id: str, provider: str) -> dict:
    async with db_session() as db:
        return await get_credentials(db, workspace_id, provider) or {}


def _svix_headers(secret: str, payload: bytes) -> dict:
    raw_key = base64.b64decode(secret.removeprefix("whsec_"))
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    ts = str(int(time.time()))
    to_sign = f"{msg_id}.{ts}.".encode() + payload
    sig = base64.b64encode(hmac.new(raw_key, to_sign, hashlib.sha256).digest()).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": f"v1,{sig}",
        "content-type": "application/json",
    }


async def cmd_reply(args) -> None:
    ws = await _workspace(args.slug)
    creds = await _creds(ws.id, "resend")
    secret = creds.get("webhook_secret", "")
    if not secret:
        raise SystemExit(
            "Workspace has no resend webhook_secret. Save one in Settings → "
            "credentials → resend, e.g.: whsec_"
            + base64.b64encode(pysecrets.token_bytes(32)).decode()
        )
    payload = json.dumps({
        "type": "email.received",
        "data": {
            "from": args.from_email,
            "subject": args.subject,
            "text": args.text,
        },
    }).encode()
    r = httpx.post(
        f"{args.base_url}/webhooks/{args.slug}/resend",
        content=payload,
        headers=_svix_headers(secret, payload),
    )
    print(r.status_code, r.text[:200])
    print("→ watch the worker: an inbound_message job runs the reply agent; "
          "the reply lands in Approvals (or auto-sends per workspace policy).")


async def cmd_delivery(args) -> None:
    ws = await _workspace(args.slug)
    creds = await _creds(ws.id, "resend")
    secret = creds.get("webhook_secret", "")
    if not secret:
        raise SystemExit("Workspace has no resend webhook_secret (see --help).")
    payload = json.dumps({
        "type": args.event,
        "data": {"email_id": args.email_id, "to": [args.to]},
    }).encode()
    r = httpx.post(
        f"{args.base_url}/webhooks/{args.slug}/resend",
        content=payload,
        headers=_svix_headers(secret, payload),
    )
    print(r.status_code, r.text[:200])
    if args.event in ("email.bounced", "email.complained"):
        print(f"→ {args.to} is now on the email suppression list.")


async def cmd_booking(args) -> None:
    ws = await _workspace(args.slug)
    creds = await _creds(ws.id, "calcom")
    secret = creds.get("webhook_secret", "")
    if not secret:
        raise SystemExit(
            "Workspace has no calcom webhook_secret. Save one in Settings → "
            "credentials → calcom (any string ≥ 16 chars works locally)."
        )
    async with db_session() as db:
        prospect = (await db.execute(
            select(Prospect).where(
                Prospect.workspace_id == ws.id,
                Prospect.email == args.prospect_email.lower(),
            )
        )).scalar_one_or_none()
    if prospect is None:
        raise SystemExit(f"No prospect {args.prospect_email!r} in this workspace")
    start = datetime.now(UTC) + timedelta(hours=args.hours_ahead)
    payload = json.dumps({
        "triggerEvent": args.trigger,
        "payload": {
            "uid": args.uid or f"sim-{uuid.uuid4().hex[:10]}",
            "title": "Intro call",
            "startTime": start.isoformat(),
            "metadata": {"prospect_id": prospect.id, "workspace_id": ws.id},
            "attendees": [{"email": prospect.email}],
        },
    }).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    r = httpx.post(
        f"{args.base_url}/webhooks/{args.slug}/calcom",
        content=payload,
        headers={"x-cal-signature-256": sig, "content-type": "application/json"},
    )
    print(r.status_code, r.text[:200])
    print("→ prospect advances to 'booked'; a reminder SMS is scheduled if "
          "the start time is within 24h and a phone is set.")


async def cmd_sms(args) -> None:
    ws = await _workspace(args.slug)
    creds = await _creds(ws.id, "africastalking")
    token = creds.get("webhook_token", "")
    if not token:
        raise SystemExit(
            "Workspace has no africastalking credential (its webhook URL "
            "token is auto-generated when you save one in Settings)."
        )
    r = httpx.post(
        f"{args.base_url}/webhooks/{args.slug}/sms/{token}",
        data={
            "from": args.from_phone,
            "text": args.text,
            "id": f"sim-{uuid.uuid4().hex[:10]}",
            "date": str(int(time.time())),
            "to": "shortcode",
        },
    )
    print(r.status_code, r.text[:200])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--slug", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reply", help="inbound email reply (Resend, Svix-signed)")
    r.add_argument("--from-email", required=True)
    r.add_argument("--subject", default="Re: your note")
    r.add_argument("--text", required=True)

    d = sub.add_parser("delivery", help="email delivery event (Resend)")
    d.add_argument("--event", default="email.bounced",
                   choices=["email.delivered", "email.opened", "email.clicked",
                            "email.bounced", "email.complained"])
    d.add_argument("--email-id", default="em_sim_1")
    d.add_argument("--to", required=True)

    b = sub.add_parser("booking", help="Cal.com booking event (HMAC-signed)")
    b.add_argument("--prospect-email", required=True)
    b.add_argument("--trigger", default="BOOKING_CREATED",
                   choices=["BOOKING_CREATED", "BOOKING_RESCHEDULED",
                            "BOOKING_CANCELLED"])
    b.add_argument("--hours-ahead", type=float, default=48)
    b.add_argument("--uid", default="")

    s = sub.add_parser("sms", help="inbound SMS (Africa's Talking URL token)")
    s.add_argument("--from-phone", required=True)
    s.add_argument("--text", required=True)

    args = p.parse_args()
    asyncio.run({"reply": cmd_reply, "delivery": cmd_delivery,
                 "booking": cmd_booking, "sms": cmd_sms}[args.cmd](args))


if __name__ == "__main__":
    main()

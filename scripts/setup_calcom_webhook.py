"""Register the workspace's Cal.com booking webhook.

Reads the calcom api_key + webhook_secret from the workspace's stored
credentials and registers BASE_URL/webhooks/<slug>/calcom for the booking
lifecycle triggers via Cal.com's v2 API. Idempotent: an existing
registration for the same URL is updated, not duplicated.

Run with the same DATABASE_URL (and BASE_URL) as the server:
    python scripts/setup_calcom_webhook.py --slug tenacious
"""
import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from engine.config import get_settings  # noqa: E402
from engine.db import db_session  # noqa: E402
from engine.models import Workspace  # noqa: E402
from engine.services.credentials import get_credentials, set_credentials  # noqa: E402

API = "https://api.cal.com/v2/webhooks"
TRIGGERS = ["BOOKING_CREATED", "BOOKING_RESCHEDULED", "BOOKING_CANCELLED"]


async def main(slug: str) -> None:
    base_url = get_settings().base_url.rstrip("/")
    if base_url.startswith("http://localhost") or "127.0.0.1" in base_url:
        raise SystemExit(
            f"BASE_URL is {base_url} — Cal.com needs a public https URL "
            "(run the tunnel and set BASE_URL, or deploy first)."
        )
    async with db_session() as db:
        ws = (await db.execute(
            select(Workspace).where(Workspace.slug == slug)
        )).scalar_one_or_none()
        if ws is None:
            raise SystemExit(f"No workspace with slug {slug!r}")
        creds = await get_credentials(db, ws.id, "calcom") or {}
        api_key = creds.get("api_key")
        if not api_key:
            raise SystemExit(
                "No calcom api_key stored — save one in Settings → "
                "Provider credentials → calcom."
            )
        secret = creds.get("webhook_secret") or secrets.token_urlsafe(24)
        webhook_url = f"{base_url}/webhooks/{slug}/calcom"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "cal-api-version": "2024-06-14",
            "Content-Type": "application/json",
        }

        listing = httpx.get(API, headers=headers, timeout=20).json()
        existing = next(
            (
                h for h in (listing.get("data") or [])
                if isinstance(h, dict)
                and h.get("subscriberUrl") == webhook_url
            ),
            None,
        )
        payload = {
            "subscriberUrl": webhook_url,
            "active": True,
            "triggers": TRIGGERS,
            "secret": secret,
        }
        if existing:
            resp = httpx.patch(
                f"{API}/{existing['id']}", headers=headers, json=payload,
                timeout=20,
            ).json()
            action = "updated"
        else:
            resp = httpx.post(API, headers=headers, json=payload, timeout=20).json()
            action = "created"
        if resp.get("status") != "success":
            raise SystemExit(f"Cal.com webhook registration failed: {resp}")

        await set_credentials(db, ws.id, "calcom",
                              {**creds, "webhook_secret": secret})
    print(f"Cal.com webhook {action}: {webhook_url}")
    print(f"Triggers: {', '.join(TRIGGERS)} (HMAC secret stored, fail-closed)")
    print("Book a slot on your event page — the prospect flips to 'booked'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.slug))

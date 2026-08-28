"""Register the workspace's Telegram bot webhook.

Reads the bot_token from the workspace's stored `telegram` credential,
fills in bot_username (via getMe) and a webhook_secret if missing, then
calls Telegram's setWebhook pointing at BASE_URL/webhooks/<slug>/telegram
with that secret — the engine's webhook route rejects requests that don't
echo it (fail closed, like every other provider).

Run with the same DATABASE_URL (and BASE_URL) as the server:
    python scripts/setup_telegram_webhook.py --slug tenacious
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

API = "https://api.telegram.org/bot{token}/{method}"


async def main(slug: str) -> None:
    base_url = get_settings().base_url.rstrip("/")
    if base_url.startswith("http://localhost") or "127.0.0.1" in base_url:
        raise SystemExit(
            f"BASE_URL is {base_url} — Telegram needs a public https URL "
            "(run the tunnel and set BASE_URL, or deploy first)."
        )
    async with db_session() as db:
        ws = (await db.execute(
            select(Workspace).where(Workspace.slug == slug)
        )).scalar_one_or_none()
        if ws is None:
            raise SystemExit(f"No workspace with slug {slug!r}")
        creds = await get_credentials(db, ws.id, "telegram") or {}
        token = creds.get("bot_token")
        if not token:
            raise SystemExit(
                "No bot_token stored. Create a bot with @BotFather and save "
                "its token in Settings → Provider credentials → telegram."
            )

        me = httpx.get(API.format(token=token, method="getMe"), timeout=15).json()
        if not me.get("ok"):
            raise SystemExit(f"Bot token rejected by Telegram: {me}")
        username = me["result"]["username"]

        secret = creds.get("webhook_secret") or secrets.token_urlsafe(32)
        webhook_url = f"{base_url}/webhooks/{slug}/telegram"
        resp = httpx.post(
            API.format(token=token, method="setWebhook"),
            json={
                "url": webhook_url,
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
            timeout=15,
        ).json()
        if not resp.get("ok"):
            raise SystemExit(f"setWebhook failed: {resp}")

        await set_credentials(db, ws.id, "telegram", {
            **creds,
            "bot_username": username,
            "webhook_secret": secret,
        })

    print(f"Bot @{username} → {webhook_url} (secret registered, fail-closed)")
    print("Next: message the bot /start — it replies with your chat id; "
          "paste that as operator_chat_id in Settings → credentials → "
          "telegram to receive operator notifications and sink-mode messages.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.slug))

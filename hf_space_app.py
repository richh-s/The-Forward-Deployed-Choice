"""Entry point for a Hugging Face Space.

Spaces run this file directly rather than a container, so it does what a
Dockerfile CMD would: apply migrations, then serve. Docker Spaces are a paid
feature, and the free SDKs give you a Python process and a proxied port —
which is all this needs, since the app is a normal ASGI application.

Port 7860 is what the Spaces proxy forwards to. The dashboard is served from
frontend/out, which is committed on the deployment branch because a Space
has no Node build step (see .gitignore — it is generated everywhere else).
"""
import logging
import os
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hf-space")

PORT = int(os.environ.get("PORT", "7860"))


def migrate() -> None:
    """Apply migrations before serving. Idempotent, so running it on every
    container start is safe — and a Space has no pre-deploy hook."""
    log.info("Applying database migrations…")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fail loudly: serving against an out-of-date schema produces
        # confusing runtime errors far from the real cause.
        log.error("Migrations failed:\n%s\n%s", result.stdout, result.stderr)
        raise SystemExit(1)
    log.info("Migrations applied.")


if __name__ == "__main__":
    migrate()
    import uvicorn

    # --proxy-headers equivalent: the Spaces proxy terminates TLS, and Twilio
    # signs the public https URL, so request.url must reflect it.
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )

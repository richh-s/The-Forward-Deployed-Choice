"""CSRF protection for the cookie-authenticated dashboard.

Two mechanisms, one dependency:

- Logged-in forms carry a stateless token derived from the session cookie
  (HMAC(app_secret, session_token)); an attacker's page can neither read
  the cookie nor forge the HMAC.
- Pre-login forms (/login, /setup) use a double-submit cookie: the GET
  handler sets a random `csrft` cookie and embeds the same value in the
  form; the POST requires them to match.

Webhook routes are signature-verified and cookie-free — they are mounted
without this dependency. The RFC 8058 unsubscribe POST is deliberately
exempt (cross-origin by design).
"""
import secrets

from fastapi import HTTPException, Request

from engine.config import get_settings
from engine.security import verify_csrf_token

PRELOGIN_COOKIE = "csrft"


def new_prelogin_token() -> str:
    return secrets.token_urlsafe(32)


def set_prelogin_cookie(response, token: str) -> None:
    response.set_cookie(
        PRELOGIN_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().is_production,
        max_age=3600,
    )


async def require_csrf(request: Request) -> None:
    """Dependency for every state-changing, cookie-authenticated route."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    form = await request.form()  # cached by Starlette; route Form() still works
    presented = str(form.get("csrf_token", ""))

    session_token = request.cookies.get(get_settings().session_cookie_name)
    if session_token and verify_csrf_token(session_token, presented):
        return

    # Fall through to the pre-login double-submit check even when a session
    # cookie is present: cookies are not isolated by port, so a stale
    # session cookie from another instance on the same host (e.g. a dev
    # server on :8000 next to this one on :8010) or from a revoked session
    # must not lock the user out of the login form itself.
    prelogin = request.cookies.get(PRELOGIN_COOKIE, "")
    if prelogin and presented and secrets.compare_digest(prelogin, presented):
        return
    raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

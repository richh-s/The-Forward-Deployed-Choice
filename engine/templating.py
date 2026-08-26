"""Shared Jinja2 template environment."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from engine.config import get_settings
from engine.security import csrf_token_for

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def csrf_field(request: Request) -> Markup:
    """Hidden CSRF input for logged-in forms; token derived from the session
    cookie (see engine/csrf.py)."""
    session_token = request.cookies.get(get_settings().session_cookie_name, "")
    token = csrf_token_for(session_token) if session_token else ""
    return Markup(
        f'<input type="hidden" name="csrf_token" value="{token}">'
    )


templates.env.globals["csrf_field"] = csrf_field

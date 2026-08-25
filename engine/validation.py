"""Small shared validators."""
import re

from email_validator import EmailNotValidError, validate_email

from engine.config import get_settings

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def valid_email(value: str) -> str | None:
    try:
        result = validate_email(
            (value or "").strip(),
            check_deliverability=False,
            # Outside production, allow reserved names (.test etc.) so
            # development and CI can use safe fake addresses.
            test_environment=not get_settings().is_production,
        )
        return result.normalized.lower()
    except EmailNotValidError:
        return None


def valid_phone(value: str) -> str | None:
    """Loose E.164 validation; returns the normalized number or None."""
    p = (value or "").strip().replace(" ", "").replace("-", "")
    if p and not p.startswith("+") and p.isdigit():
        p = "+" + p
    return p if E164_RE.match(p) else None

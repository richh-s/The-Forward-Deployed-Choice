"""Per-workspace provider credential access."""
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import WorkspaceCredential
from engine.security import decrypt_credentials, encrypt_credentials

logger = logging.getLogger(__name__)

# Allowed fields per provider — enforced on write, not just a UI hint.
PROVIDER_FIELDS: dict[str, list[str]] = {
    "resend": ["api_key", "webhook_secret"],
    "hubspot": ["access_token", "webhook_secret"],
    "calcom": ["api_key", "webhook_secret", "base_url"],
    "africastalking": ["username", "api_key", "webhook_token", "sales_phone"],
    "twilio": ["account_sid", "auth_token", "from_number", "sales_phone"],
    "anthropic": ["api_key", "workspace_id"],
    # Signal source for prospects: POST {email, name, company, title, phone}
    # → {"signals": {...}} (see engine/services/enrichment.py).
    "enrichment": ["url", "api_key"],
    # Slack incoming webhook for operator notifications (drafts awaiting
    # review, escalations, kill-switch pauses, weekly digest).
    "slack": ["webhook_url"],
    # Telegram bot (free, no carrier): operator notifications AND a
    # conversational prospect channel. webhook_secret is echoed by Telegram
    # in X-Telegram-Bot-Api-Secret-Token; operator_chat_id receives
    # notifications and sink-mode messages.
    "telegram": ["bot_token", "bot_username", "operator_chat_id",
                 "webhook_secret"],
}


class CredentialValidationError(ValueError):
    pass


def _assert_public_host(url_field: str, value: str) -> None:
    """Reject URLs whose host is (or resolves to) a private, link-local,
    or otherwise non-public address — a tenant admin must not be able to
    aim server-side requests at cloud metadata or internal services.

    Loopback stays allowed outside production (the local enrichment
    service in development). Hostnames are resolved at save time; a name
    that does not resolve is allowed through (the request will fail on its
    own), so this is defense-in-depth, not a substitute for network
    egress policy — `follow_redirects=False` on the shared client closes
    the redirect variant.
    """
    from engine.config import get_settings

    settings = get_settings()
    host = (urlsplit(value).hostname or "").strip("[]")
    if not host:
        raise CredentialValidationError(f"{url_field} has no host")
    is_loopback_name = host == "localhost"
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            addrs = [ipaddress.ip_address(info[4][0]) for info in infos]
        except (socket.gaierror, ValueError):
            return  # unresolvable — let the actual request fail
    for addr in addrs:
        if addr.is_loopback or is_loopback_name:
            if settings.is_production:
                raise CredentialValidationError(
                    f"{url_field} must not point at loopback in production"
                )
            continue
        if not addr.is_global:
            raise CredentialValidationError(
                f"{url_field} must point at a public host "
                f"(got {addr} for {host!r})"
            )


def validate_credential_payload(provider: str, payload: dict) -> dict:
    """Drop unknown keys and reject dangerous values.

    - `base_url` must be https and points at a public API host (a tenant
      admin must not be able to aim server-side requests at internal
      addresses — SSRF).
    - `webhook_token` (the Africa's Talking URL auth) can't be downgraded
      to something guessable.
    """
    allowed = PROVIDER_FIELDS.get(provider)
    if allowed is None:
        raise CredentialValidationError(f"Unknown provider {provider!r}")
    unknown = [k for k in payload if k not in allowed]
    if unknown:
        # A typo'd field name silently dropped would report "saved" while
        # storing nothing — every later send fails with no UI trace.
        raise CredentialValidationError(
            f"Unknown field(s) for {provider}: {', '.join(sorted(unknown))} "
            f"— expected: {', '.join(allowed)}"
        )
    cleaned = {
        k: str(v).strip() for k, v in payload.items()
        if v is not None and str(v).strip()
    }
    if not cleaned:
        raise CredentialValidationError(
            f"No credential values provided for {provider}"
        )
    for url_field in ("base_url", "url", "webhook_url"):
        value = cleaned.get(url_field, "")
        if not value:
            continue
        # https everywhere; plain http tolerated only for loopback (the
        # local enrichment service in development) — never for arbitrary
        # hosts, which would reopen SSRF via tenant config.
        is_loopback_http = value.startswith(
            ("http://localhost", "http://127.0.0.1")
        )
        if not value.startswith("https://") and not is_loopback_http:
            raise CredentialValidationError(
                f"{url_field} must be an https:// URL"
            )
        _assert_public_host(url_field, value)
    token = cleaned.get("webhook_token", "")
    if token and len(token) < 16:
        raise CredentialValidationError(
            "webhook_token must be at least 16 characters"
        )
    return cleaned


async def get_credentials(
    db: AsyncSession, workspace_id: str, provider: str
) -> dict | None:
    row = await db.execute(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == workspace_id,
            WorkspaceCredential.provider == provider,
        )
    )
    cred = row.scalar_one_or_none()
    if cred is None:
        return None
    try:
        return decrypt_credentials(cred.encrypted_payload)
    except ValueError:
        # Wrong/rotated APP_SECRET_KEY. Treating this as "not configured"
        # (with a loud log) keeps webhooks answering 401-blocked instead of
        # 500 — a 500 makes providers retry forever, and it would also take
        # down the Settings page an admin needs to re-enter the credentials.
        logger.error(
            "Could not decrypt %s credentials for workspace %s — was "
            "APP_SECRET_KEY rotated without APP_SECRET_KEY_OLD?",
            provider, workspace_id,
        )
        return None


async def set_credentials(
    db: AsyncSession, workspace_id: str, provider: str, payload: dict
) -> None:
    if provider not in PROVIDER_FIELDS:
        raise ValueError(f"Unknown provider {provider!r}")
    row = await db.execute(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == workspace_id,
            WorkspaceCredential.provider == provider,
        )
    )
    cred = row.scalar_one_or_none()
    encrypted = encrypt_credentials(payload)
    if cred is None:
        db.add(
            WorkspaceCredential(
                workspace_id=workspace_id,
                provider=provider,
                encrypted_payload=encrypted,
            )
        )
    else:
        cred.encrypted_payload = encrypted


async def configured_providers(db: AsyncSession, workspace_id: str) -> list[str]:
    rows = await db.execute(
        select(WorkspaceCredential.provider).where(
            WorkspaceCredential.workspace_id == workspace_id
        )
    )
    return [r[0] for r in rows.all()]

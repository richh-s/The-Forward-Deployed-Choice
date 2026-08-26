"""Per-workspace provider credential access."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import WorkspaceCredential
from engine.security import decrypt_credentials, encrypt_credentials

# Allowed fields per provider — enforced on write, not just a UI hint.
PROVIDER_FIELDS: dict[str, list[str]] = {
    "resend": ["api_key", "webhook_secret"],
    "hubspot": ["access_token", "webhook_secret"],
    "calcom": ["api_key", "webhook_secret", "base_url"],
    "africastalking": ["username", "api_key", "webhook_token", "sales_phone"],
    "twilio": ["account_sid", "auth_token", "from_number", "sales_phone"],
    "anthropic": ["api_key"],
}


class CredentialValidationError(ValueError):
    pass


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
    cleaned = {
        k: str(v).strip() for k, v in payload.items()
        if k in allowed and v is not None and str(v).strip()
    }
    base_url = cleaned.get("base_url", "")
    if base_url and not base_url.startswith("https://"):
        raise CredentialValidationError("base_url must be an https:// URL")
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
    return decrypt_credentials(cred.encrypted_payload)


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

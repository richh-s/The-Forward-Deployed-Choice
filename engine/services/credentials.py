"""Per-workspace provider credential access."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import WorkspaceCredential
from engine.security import decrypt_credentials, encrypt_credentials

# Fields expected per provider — used by the settings UI for validation hints.
PROVIDER_FIELDS: dict[str, list[str]] = {
    "resend": ["api_key", "webhook_secret"],
    "hubspot": ["access_token", "webhook_secret"],
    "calcom": ["api_key", "webhook_secret", "base_url"],
    "africastalking": ["username", "api_key"],
    "twilio": ["account_sid", "auth_token", "from_number"],
    "anthropic": ["api_key"],
}


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

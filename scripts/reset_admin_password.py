"""Break-glass password reset for a locked-out account (e.g. the only admin).

Runs against the configured DATABASE_URL with direct DB access — this is the
recovery path when nobody can log in, so it deliberately lives outside the
web app. The user must set their own password at next login, and every
existing session for the account is revoked.

    python scripts/reset_admin_password.py --email admin@client.com
"""
import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from engine.auth import destroy_all_sessions  # noqa: E402
from engine.db import db_session  # noqa: E402
from engine.models import AuditLog, User  # noqa: E402
from engine.security import hash_password_async  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="account to reset")
    args = parser.parse_args()

    async with db_session() as db:
        user = (await db.execute(
            select(User).where(User.email == args.email.strip().lower())
        )).scalar_one_or_none()
        if user is None:
            print(f"No user with email {args.email!r}", file=sys.stderr)
            return 1
        temp_password = secrets.token_urlsafe(12)
        user.password_hash = await hash_password_async(temp_password)
        user.must_change_password = True
        user.is_active = True
        revoked = await destroy_all_sessions(db, user.id)
        db.add(AuditLog(
            workspace_id=user.workspace_id,
            action="password_reset",
            detail={"target_user": user.email, "via": "cli", "sessions_revoked": revoked},
        ))
    print(f"Temporary password for {user.email}: {temp_password}")
    print(f"Revoked {revoked} session(s). They must set a new password at login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

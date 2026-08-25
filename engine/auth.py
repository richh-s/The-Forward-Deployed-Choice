"""Authentication dependencies for dashboard and API routes."""
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.db import get_db
from engine.models import AuthSession, User, Workspace, as_aware, utcnow
from engine.security import hash_session_token, new_session_token


class AuthContext:
    def __init__(self, user: User, workspace: Workspace):
        self.user = user
        self.workspace = workspace


async def create_session(db: AsyncSession, user: User) -> str:
    """Create a DB-backed session; returns the raw token for the cookie."""
    settings = get_settings()
    token = new_session_token()
    db.add(
        AuthSession(
            token_hash=hash_session_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    user.last_login_at = utcnow()
    return token


async def destroy_session(db: AsyncSession, token: str) -> None:
    await db.execute(
        delete(AuthSession).where(
            AuthSession.token_hash == hash_session_token(token)
        )
    )


async def _resolve_session(db: AsyncSession, token: str) -> AuthContext | None:
    row = await db.execute(
        select(AuthSession).where(
            AuthSession.token_hash == hash_session_token(token)
        )
    )
    session = row.scalar_one_or_none()
    if session is None or as_aware(session.expires_at) < utcnow():
        return None
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None:
        return None
    return AuthContext(user, workspace)


async def current_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthContext:
    """Require a logged-in user. Raises 401 (API) — UI routes redirect on 401."""
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    ctx = await _resolve_session(db, token)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return ctx


async def current_admin(ctx: AuthContext = Depends(current_auth)) -> AuthContext:
    if ctx.user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return ctx


async def optional_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthContext | None:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    return await _resolve_session(db, token)

"""Login, logout, and first-run setup."""
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import create_session, destroy_session
from engine.config import get_settings
from engine.db import get_db
from engine.models import AuditLog, User, Workspace
from engine.security import hash_password, verify_password
from engine.templating import templates
from engine.validation import valid_email

router = APIRouter()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


async def _no_users_yet(db: AsyncSession) -> bool:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    return int(count) == 0


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if await _no_users_yet(db):
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": request.query_params.get("error", "")}
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    addr = valid_email(email)
    user = None
    if addr:
        row = await db.execute(select(User).where(User.email == addr))
        user = row.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(
        password, user.password_hash
    ):
        return RedirectResponse("/login?error=Invalid+credentials", status_code=303)

    token = await create_session(db, user)
    response = RedirectResponse("/", status_code=303)
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_ttl_hours * 3600,
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await destroy_session(db, token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not await _no_users_yet(db):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "setup.html", {"error": request.query_params.get("error", "")}
    )


@router.post("/setup")
async def setup(
    request: Request,
    workspace_name: str = Form(...),
    admin_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """First-run bootstrap: create the first workspace and its admin.
    Disabled forever after the first user exists."""
    if not await _no_users_yet(db):
        return RedirectResponse("/login", status_code=303)
    addr = valid_email(email)
    if not addr:
        return RedirectResponse("/setup?error=Invalid+email", status_code=303)
    if len(password) < 10:
        return RedirectResponse(
            "/setup?error=Password+must+be+at+least+10+characters", status_code=303
        )
    workspace = Workspace(name=workspace_name.strip(), slug=slugify(workspace_name))
    db.add(workspace)
    await db.flush()
    user = User(
        workspace_id=workspace.id,
        email=addr,
        name=admin_name.strip(),
        password_hash=hash_password(password),
        role="admin",
    )
    db.add(user)
    db.add(
        AuditLog(workspace_id=workspace.id, action="workspace_created",
                 detail={"name": workspace.name})
    )
    await db.flush()

    token = await create_session(db, user)
    response = RedirectResponse("/settings?welcome=1", status_code=303)
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_ttl_hours * 3600,
    )
    return response

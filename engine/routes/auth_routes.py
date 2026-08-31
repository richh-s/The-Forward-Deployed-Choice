"""Login, logout, and first-run setup."""
import logging
import re
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import create_session, destroy_session
from engine.config import get_settings
from engine.csrf import new_prelogin_token, require_csrf, set_prelogin_cookie
from engine.db import get_db
from engine.models import AuditLog, User, Workspace
from engine.ratelimit import check_login_rate, check_public_rate, client_ip
from engine.security import (
    equalize_verify_timing,
    hash_password_async,
    verify_password_async,
)
from engine.templating import templates
from engine.validation import valid_email

logger = logging.getLogger(__name__)
router = APIRouter()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


async def _no_users_yet(db: AsyncSession) -> bool:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    return int(count) == 0


def _set_session_cookie(response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_ttl_hours * 3600,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if await _no_users_yet(db):
        return RedirectResponse("/setup", status_code=303)
    csrf_token = new_prelogin_token()
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"error": request.query_params.get("error", ""), "csrf_token": csrf_token},
    )
    set_prelogin_cookie(response, csrf_token)
    return response


@router.post("/login", dependencies=[Depends(require_csrf)])
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    await check_login_rate(request, email)
    addr = valid_email(email)
    user = None
    if addr:
        row = await db.execute(select(User).where(User.email == addr))
        user = row.scalar_one_or_none()
    if user is None:
        # Same bcrypt cost as a real verification — no timing oracle for
        # whether the email exists.
        await equalize_verify_timing()
        ok = False
    else:
        ok = user.is_active and await verify_password_async(
            password, user.password_hash
        )
    if not ok:
        db.add(AuditLog(
            workspace_id=user.workspace_id if user else None,
            action="login_failed",
            detail={"email": addr or email[:100], "ip": client_ip(request)},
        ))
        return RedirectResponse("/login?error=Invalid+credentials", status_code=303)

    token = await create_session(db, user)
    db.add(AuditLog(
        workspace_id=user.workspace_id, user_id=user.id,
        action="login_success", detail={"ip": client_ip(request)},
    ))
    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(response, token)
    return response


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await destroy_session(db, token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )
    return response


def _setup_allowed(presented_token: str) -> None:
    """In production the one-shot bootstrap additionally requires the
    deploy-time SETUP_TOKEN, so 'first visitor becomes admin' is impossible
    on a freshly migrated database."""
    settings = get_settings()
    if not settings.is_production:
        return
    if not settings.setup_token:
        raise HTTPException(
            status_code=403,
            detail="Setup is disabled: SETUP_TOKEN is not configured",
        )
    if not secrets.compare_digest(settings.setup_token, presented_token):
        raise HTTPException(status_code=403, detail="Invalid setup token")


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    await check_public_rate(request, "setup")
    if not await _no_users_yet(db):
        return RedirectResponse("/login", status_code=303)
    csrf_token = new_prelogin_token()
    response = templates.TemplateResponse(
        request,
        "setup.html",
        {
            "error": request.query_params.get("error", ""),
            "csrf_token": csrf_token,
            "needs_setup_token": get_settings().is_production,
        },
    )
    set_prelogin_cookie(response, csrf_token)
    return response


@router.post("/setup", dependencies=[Depends(require_csrf)])
async def setup(
    request: Request,
    workspace_name: str = Form(...),
    admin_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    setup_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """First-run bootstrap: create the first workspace and its admin.
    Disabled forever after the first user exists."""
    await check_public_rate(request, "setup")
    _setup_allowed(setup_token)

    # Serialize concurrent bootstraps: on Postgres take a transaction-scoped
    # advisory lock before the users count, so two racing POSTs cannot both
    # observe an empty table.
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('engine-setup'))"))

    if not await _no_users_yet(db):
        return RedirectResponse("/login", status_code=303)
    addr = valid_email(email)
    if not addr:
        return RedirectResponse("/setup?error=Invalid+email", status_code=303)
    if len(password) < 10:
        return RedirectResponse(
            "/setup?error=Password+must+be+at+least+10+characters", status_code=303
        )
    slug = slugify(workspace_name)
    taken = (await db.execute(
        select(Workspace.id).where(Workspace.slug == slug)
    )).first()
    if taken:
        slug = f"{slug}-{secrets.token_hex(3)}"
    workspace = Workspace(name=workspace_name.strip(), slug=slug)
    db.add(workspace)
    await db.flush()
    user = User(
        workspace_id=workspace.id,
        email=addr,
        name=admin_name.strip(),
        password_hash=await hash_password_async(password),
        role="admin",
    )
    db.add(user)
    db.add(
        AuditLog(workspace_id=workspace.id, action="workspace_created",
                 detail={"name": workspace.name, "ip": client_ip(request)})
    )
    await db.flush()

    token = await create_session(db, user)
    response = RedirectResponse("/settings?welcome=1", status_code=303)
    _set_session_cookie(response, token)
    return response

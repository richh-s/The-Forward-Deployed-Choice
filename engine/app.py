"""Application factory."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import func, select, text
from starlette.staticfiles import StaticFiles

from engine.config import get_settings
from engine.csrf import require_csrf
from engine.db import db_session, dispose_engine
from engine.middleware import (
    BodySizeLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from engine.observability import configure_logging, init_sentry
from engine.queue import heartbeats, recover_stuck_jobs, worker_loop
from engine.services import jobs as _jobs  # noqa: F401 — registers job handlers
from engine.services.http import close_client
from engine.services.scheduler import scheduler_loop
from engine.services.tracing import init_tracing, shutdown_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        # Dev/test convenience only — Postgres deployments run
        # `alembic upgrade head` (see render.yaml preDeploy).
        from engine import models  # noqa: F401
        from engine.db import Base, get_engine

        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.run_worker:
        await recover_stuck_jobs()
        concurrency = (
            1 if settings.database_url.startswith("sqlite")
            else max(1, settings.worker_concurrency)
        )
        for i in range(concurrency):
            name = f"worker-{i}"
            tasks.append(asyncio.create_task(
                worker_loop(stop_event, name=name), name=name
            ))
        tasks.append(asyncio.create_task(scheduler_loop(stop_event), name="scheduler"))
    try:
        yield
    finally:
        # Graceful drain: signal loops to stop, give in-flight jobs a grace
        # window to finish, then cancel whatever is left.
        stop_event.set()
        if tasks:
            done, pending = await asyncio.wait(
                tasks, timeout=settings.shutdown_grace_seconds
            )
            for task in pending:
                logger.warning("Cancelling task %s after drain window", task.get_name())
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await close_client()
        shutdown_tracing()
        await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()
    init_sentry()
    init_tracing()
    settings = get_settings()  # validators fail fast on unsafe production config

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    # add_middleware prepends: last added runs outermost. Effective order is
    # RequestID → SecurityHeaders → BodySizeLimit → app, so the body
    # limiter's own 413 still passes through the security-header and
    # request-id wrappers.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)

    from pathlib import Path

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from engine.routes.api import router as api_router
    from engine.routes.auth_routes import router as auth_router
    from engine.routes.dashboard import router as dashboard_router
    from engine.routes.json_api import router as json_api_router
    from engine.routes.webhooks import router as webhooks_router

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    # Read-only JSON API for the Next.js dashboard (GET-only; session-auth'd
    # via the same cookie — writes go through the CSRF-gated form routes).
    app.include_router(json_api_router)

    # The Next.js dashboard, when built (cd frontend && npm run build) —
    # a static export served same-origin at /app. Absent in dev/CI unless
    # built; the server-rendered dashboard at / is unaffected either way.
    next_dir = Path(__file__).parent.parent / "frontend" / "out"
    if next_dir.is_dir():
        app.mount(
            "/app", StaticFiles(directory=str(next_dir), html=True), name="next"
        )
    # Every dashboard action route is a cookie-authenticated form POST —
    # CSRF-protect the whole router. Webhooks are signature-verified and
    # cookie-free, so they are mounted without it.
    app.include_router(api_router, dependencies=[Depends(require_csrf)])
    app.include_router(webhooks_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        """Liveness AND readiness: DB reachable, and (when this instance
        runs them) worker/scheduler loops recently alive."""
        from engine.models import as_aware, utcnow

        checks: dict[str, str] = {}
        healthy = True
        try:
            async with db_session() as db:
                await db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {type(exc).__name__}"
            healthy = False

        if settings.run_worker:
            now = utcnow()
            worker_beats = [
                as_aware(ts) for name, ts in heartbeats.items()
                if name.startswith("worker")
            ]
            worker_stale = max(60.0, settings.worker_poll_seconds * 10)
            if worker_beats and (
                (now - max(worker_beats)).total_seconds() < worker_stale
            ):
                checks["worker"] = "ok"
            else:
                checks["worker"] = "stale"
                healthy = False
            sched = heartbeats.get("scheduler")
            if sched is not None and (
                (now - as_aware(sched)).total_seconds()
                < settings.scheduler_interval_seconds * 3
            ):
                checks["scheduler"] = "ok"
            else:
                checks["scheduler"] = "stale"
                healthy = False

        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "service": "conversion-engine",
                "checks": checks,
            },
        )

    @app.get("/health/live")
    async def health_live() -> dict:
        """Bare process liveness (no dependencies touched)."""
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> PlainTextResponse:
        """Minimal Prometheus-format metrics, no client library needed.
        Protected by METRICS_TOKEN; disabled in production without one."""
        if settings.metrics_token:
            auth_header = request.headers.get("authorization", "")
            if auth_header != f"Bearer {settings.metrics_token}":
                raise HTTPException(status_code=401, detail="Unauthorized")
        elif settings.is_production:
            raise HTTPException(status_code=404)

        from datetime import timedelta

        from engine.models import Job, Message, Workspace, utcnow

        lines = []
        async with db_session() as db:
            rows = await db.execute(
                select(Job.status, func.count()).group_by(Job.status)
            )
            for status, count in rows.all():
                lines.append(
                    f'engine_jobs_total{{status="{status}"}} {count}'
                )
            # Queue lag, visible from the web tier (DB-derived, not
            # process-local heartbeats): a dead or wedged worker shows up
            # as a growing runnable backlog. Alert on
            # engine_jobs_oldest_runnable_age_seconds.
            now = utcnow()
            runnable = Job.status.in_(["pending", "failed"]) & (
                Job.run_after <= now
            )
            depth = (await db.execute(
                select(func.count()).select_from(Job).where(runnable)
            )).scalar_one()
            lines.append(f"engine_jobs_runnable {depth}")
            oldest = (await db.execute(
                select(func.min(Job.run_after)).where(runnable)
            )).scalar_one()
            from engine.models import as_aware

            age = (now - as_aware(oldest)).total_seconds() if oldest else 0.0
            lines.append(
                f"engine_jobs_oldest_runnable_age_seconds {age:.0f}"
            )
            day_ago = utcnow() - timedelta(hours=24)
            out_24h = (await db.execute(
                select(func.count()).select_from(Message).where(
                    Message.direction == "out", Message.created_at >= day_ago
                )
            )).scalar_one()
            lines.append(f"engine_messages_out_24h {out_24h}")
            paused = (await db.execute(
                select(func.count()).select_from(Workspace).where(
                    Workspace.outbound_paused.is_(True)
                )
            )).scalar_one()
            lines.append(f"engine_workspaces_paused {paused}")
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Browser navigation to a protected page → login redirect;
        # API/webhook callers get JSON.
        wants_html = "text/html" in request.headers.get("accept", "")
        if exc.status_code == 401 and wants_html:
            return RedirectResponse("/login", status_code=303)
        # Redirect-style exceptions (e.g. the forced-password-change gate)
        # carry their target in a Location header — honor it.
        location = (exc.headers or {}).get("Location")
        if exc.status_code in (302, 303, 307) and location:
            return RedirectResponse(location, status_code=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Without this, unhandled 500s are logged by uvicorn's own logger in
        # plain format, bypassing the JSON formatter and losing the
        # request_id — searches by correlation id would miss every 500.
        from engine.middleware import _BodyTooLarge

        if isinstance(exc, _BodyTooLarge):
            raise exc  # let BodySizeLimitMiddleware answer with its 413
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500, content={"detail": "Internal Server Error"}
        )

    return app

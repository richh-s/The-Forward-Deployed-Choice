"""Application factory."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from engine.config import get_settings
from engine.db import dispose_engine
from engine.queue import recover_stuck_jobs, worker_loop
from engine.services import jobs as _jobs  # noqa: F401 — registers job handlers
from engine.services.scheduler import scheduler_loop


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


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
        tasks.append(asyncio.create_task(worker_loop(stop_event), name="worker"))
        tasks.append(asyncio.create_task(scheduler_loop(stop_event), name="scheduler"))
    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_engine()


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()

    if settings.is_production and settings.app_secret_key == "dev-secret-change-me":
        raise RuntimeError(
            "APP_SECRET_KEY must be set to a strong random value in production"
        )

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    from pathlib import Path

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from engine.routes.api import router as api_router
    from engine.routes.auth_routes import router as auth_router
    from engine.routes.dashboard import router as dashboard_router
    from engine.routes.webhooks import router as webhooks_router

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(api_router)
    app.include_router(webhooks_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "conversion-engine"}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Browser navigation to a protected page → login redirect;
        # API/webhook callers get JSON.
        wants_html = "text/html" in request.headers.get("accept", "")
        if exc.status_code == 401 and wants_html:
            return RedirectResponse("/login", status_code=303)
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}
        )

    return app

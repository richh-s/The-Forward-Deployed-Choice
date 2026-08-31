"""Standalone worker process: job queue + scheduler, no HTTP.

Run with `python -m worker`. Deployments that keep RUN_WORKER=true on the
web service don't need this; the dedicated worker keeps slow LLM jobs off
the web event loop and lets the two tiers scale independently.
"""
import asyncio
import logging
import signal

from engine.config import get_settings
from engine.observability import configure_logging, init_sentry
from engine.queue import recover_stuck_jobs, worker_loop
from engine.services import jobs as _jobs  # noqa: F401 — registers handlers
from engine.services.http import close_client
from engine.services.scheduler import scheduler_loop
from engine.services.tracing import init_tracing, shutdown_tracing

logger = logging.getLogger("worker")


async def main() -> None:
    configure_logging()
    init_sentry()
    init_tracing()
    settings = get_settings()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await recover_stuck_jobs()
    concurrency = (
        1 if settings.database_url.startswith("sqlite")
        else max(1, settings.worker_concurrency)
    )
    tasks = [
        asyncio.create_task(worker_loop(stop_event, name=f"worker-{i}"))
        for i in range(concurrency)
    ]
    tasks.append(asyncio.create_task(scheduler_loop(stop_event)))
    logger.info("Worker process up: %d job slots + scheduler", concurrency)

    # Wake on shutdown signal OR on any loop dying unexpectedly — a dead
    # loop must crash the process so the supervisor restarts it, not linger
    # behind a healthy-looking process.
    stop_task = asyncio.create_task(stop_event.wait())
    await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
    crashed = not stop_event.is_set()
    if crashed:
        logger.error("A worker/scheduler loop exited unexpectedly; restarting")
        stop_event.set()

    logger.info("Draining for %.0fs", settings.shutdown_grace_seconds)
    done, pending = await asyncio.wait(
        tasks, timeout=settings.shutdown_grace_seconds
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    stop_task.cancel()

    from engine.db import dispose_engine

    await close_client()
    # Flush buffered traces last, after the loops have stopped.
    shutdown_tracing()
    await dispose_engine()
    if crashed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

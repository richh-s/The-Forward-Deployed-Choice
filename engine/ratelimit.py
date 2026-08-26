"""In-memory sliding-window rate limiting.

Per-process by design: the deployment runs a small number of instances, and
the endpoints this protects (login, setup, unsubscribe) only need abuse
resistance, not a globally exact count. Swap the store for Redis if the
fleet grows.
"""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

from engine.config import get_settings


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._last_gc = 0.0

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_gc > self.window:
                self._gc(now)
                self._last_gc = now
            q = self._events[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True

    def _gc(self, now: float) -> None:
        stale = [
            k for k, q in self._events.items()
            if not q or now - q[-1] > self.window
        ]
        for k in stale:
            del self._events[k]


_limiters: dict[str, SlidingWindowLimiter] = {}


def _limiter(name: str, max_events: int, window: float) -> SlidingWindowLimiter:
    if name not in _limiters:
        _limiters[name] = SlidingWindowLimiter(max_events, window)
    return _limiters[name]


def client_ip(request: Request) -> str:
    # uvicorn is run with --proxy-headers behind the platform proxy, so
    # request.client reflects X-Forwarded-For from the trusted hop.
    return request.client.host if request.client else "unknown"


def check_login_rate(request: Request, email: str) -> None:
    """Throttle by IP and by IP+account so neither a spray across accounts
    nor a focused attack on one account gets unlimited bcrypt attempts."""
    settings = get_settings()
    ip = client_ip(request)
    per_target = _limiter(
        "login-target",
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    )
    per_ip = _limiter(
        "login-ip",
        settings.login_rate_limit_attempts * 4,
        settings.login_rate_limit_window_seconds,
    )
    if not per_ip.allow(ip) or not per_target.allow(f"{ip}:{email.lower()}"):
        raise HTTPException(
            status_code=429, detail="Too many login attempts; try again later"
        )


def check_public_rate(request: Request, bucket: str) -> None:
    """Generic throttle for unauthenticated endpoints (/u/*, /setup)."""
    settings = get_settings()
    limiter = _limiter(
        f"public-{bucket}",
        settings.public_rate_limit_requests,
        settings.public_rate_limit_window_seconds,
    )
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests")


def reset_all() -> None:
    """Test helper."""
    _limiters.clear()

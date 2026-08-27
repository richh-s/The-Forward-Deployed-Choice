"""ASGI middleware: security headers, request correlation, body-size limits.

Kept as pure ASGI (not BaseHTTPMiddleware) so streaming and background
behavior are untouched.
"""
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from engine.config import get_settings
from engine.observability import new_request_id, request_id_var

_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.hsts = get_settings().is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy", _CSP.encode()),
                ])
                if self.hsts:
                    headers.append((
                        b"strict-transport-security",
                        b"max-age=63072000; includeSubDomains",
                    ))
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestIDMiddleware:
    """Accept X-Request-ID from the fronting proxy or mint one; expose it in
    the response and in every log line via the contextvar."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = ""
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")[:64]
                break
        rid = incoming or new_request_id()
        token = request_id_var.set(rid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-request-id", rid.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before they are buffered.

    Content-Length is checked up front; chunked/streamed bodies are counted
    as they arrive. Paths in `generous_prefixes` (CSV upload) get the higher
    limit; route-level checks still apply their own caps."""

    def __init__(self, app: ASGIApp, generous_prefixes: tuple[str, ...] = ("/campaigns",)):
        self.app = app
        settings = get_settings()
        self.default_limit = settings.max_body_bytes
        self.generous_limit = max(settings.max_body_bytes, 6 * 1024 * 1024)
        self.generous_prefixes = generous_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        limit = (
            self.generous_limit
            if any(path.startswith(p) for p in self.generous_prefixes)
            else self.default_limit
        )
        declared = 0
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                break
        if declared > limit:
            await _reject_413(send)
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            # Only answer if the app hasn't already started a response —
            # a second http.response.start is an ASGI protocol violation.
            if not response_started:
                await _reject_413(send)


class _BodyTooLarge(Exception):
    pass


async def _reject_413(send: Send) -> None:
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"detail":"Request body too large"}',
    })

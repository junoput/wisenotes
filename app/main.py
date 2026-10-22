import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import logs
from app.routes import api
from app.routes import pages

app = FastAPI(title="Wisenotes")
logs.configure()
request_logger = logging.getLogger("wisenotes.request")
# Probes are not events (docs/OBSERVABILITY.md, health).
UNLOGGED_PATHS = {"/health"}


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logging.exception("Unhandled error handling %s %s", request.method, request.scope["path"])
        return PlainTextResponse("Internal Server Error", status_code=500)

    if request.url.path.endswith(".js"):
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    if request.url.path.startswith("/static/"):
        # Revalidate every time (a 304 when unchanged): a module app.js imports has no
        # version query, and a heuristically cached copy hid deploys (20261021-011).
        response.headers["Cache-Control"] = "no-cache"

    csp = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-hashes'; "
        "script-src-attr 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


# Declared after set_security_headers, so it wraps it and logs the 500 that one
# answers for an unhandled error.
@app.middleware("http")
async def log_request(request: Request, call_next):
    """One record per request, carrying a correlation id that every record logged
    while serving it carries too. The routed path only: request.url is rebuilt
    from the Host header the client sends, and the query string can hold what a
    person typed (docs/OBSERVABILITY.md, the leak rules)."""
    path = request.scope["path"]
    token = logs.correlation_id.set(uuid.uuid4().hex)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        if path not in UNLOGGED_PATHS:
            route = request.scope.get("route")
            status = response.status_code
            request_logger.log(
                logs.request_severity(status),
                "%s %s %s",
                request.method,
                path,
                status,
                extra={
                    "attrs": {
                        "http.request.method": request.method,
                        "url.path": path,
                        "http.route": getattr(route, "path", None),
                        "http.response.status_code": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
        return response
    finally:
        logs.correlation_id.reset(token)


static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/health")
async def health():
    return PlainTextResponse("ok")


app.include_router(api.router)
app.include_router(pages.router)

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import write_fence
from app.config import get_settings
from app.routes import api
from app.routes import pages

app = FastAPI(title="Wisenotes")
logging.basicConfig(level=logging.INFO)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# Declared before the headers middleware, so that one wraps this one's 503 too.
@app.middleware("http")
async def write_fence_check(request: Request, call_next):
    """Refuse a write unless this container is the one named to write (app/write_fence.py).

    The shared lock is held until the handler has finished, so a deploy that
    changes the writer waits for this write instead of overlapping it."""
    if request.method in SAFE_METHODS:
        return await call_next(request)
    fd, allowed = await run_in_threadpool(write_fence.acquire, get_settings().data_dir)
    if not allowed:
        return PlainTextResponse(
            "Wisenotes is switching to a new version and this copy no longer saves changes. "
            "Try again in a moment.",
            status_code=503,
            headers={"Retry-After": "2"},
        )
    try:
        return await call_next(request)
    finally:
        write_fence.release(fd)


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logging.exception("Unhandled error handling %s %s", request.method, request.url.path)
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


static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/health")
async def health():
    return PlainTextResponse("ok")


app.include_router(api.router)
app.include_router(pages.router)

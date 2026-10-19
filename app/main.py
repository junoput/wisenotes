import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.routes import api
from app.routes import pages

app = FastAPI(title="Wisenotes")
logging.basicConfig(level=logging.INFO)


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logging.exception("Unhandled error handling %s %s", request.method, request.url.path)
        return PlainTextResponse("Internal Server Error", status_code=500)

    if request.url.path.endswith(".js"):
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"

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

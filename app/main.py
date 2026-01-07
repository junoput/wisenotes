from pathlib import Path

import logging
from fastapi import FastAPI, Request
import os
import base64
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.routes import api, pages

app = FastAPI(title="Wisenotes")
settings = get_settings()
logging.basicConfig(level=logging.INFO)

@app.middleware("http")
async def set_security_headers(request: Request, call_next):  # type: ignore[override]
    # Generate a per-request nonce and attach it to the request state so templates can use it
    raw = os.urandom(16)
    nonce = base64.b64encode(raw).decode('ascii')
    request.state.csp_nonce = nonce
    response = await call_next(request)
    
    # Ensure JavaScript files have correct Content-Type (critical for ES modules)
    if request.url.path.endswith('.js'):
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    
    # Build CSP and include the nonce for inline scripts
    csp = (
        "default-src 'self'; "
        # Allow inline handlers (hx-on) via nonce or hashes; include unsafe-inline on attrs for compatibility
        f"script-src 'self' https://unpkg.com https://cdn.jsdelivr.net 'nonce-{nonce}' 'unsafe-hashes'; "
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


app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

app.include_router(pages.router)
app.include_router(api.router)


@app.get("/health", response_class=HTMLResponse)
async def health():
    return "ok"

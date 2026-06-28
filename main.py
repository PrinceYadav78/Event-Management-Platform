import os
import asyncio
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from database import engine, Base, get_db
from models import models
from routers import events, students, houses, certificates, auth, dashboard, settings, admins, audit_log, account
from init_db import init_db
# Importing firestore_sync registers the SQLAlchemy commit hooks that push each
# individual change to Firestore synchronously (see firestore_sync.py).
from firestore_sync import hydrate_from_firestore, SyncError
from csrf import csrf_protect, new_token
import live
import realtime

Base.metadata.create_all(bind=engine)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

app = FastAPI(title="National Public School - Events Manager")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Issue a CSRF token cookie (JS-readable) if the visitor doesn't have one yet.
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", new_token(), max_age=60 * 60 * 24 * 30,
                            samesite="lax", secure=COOKIE_SECURE)
    return response


_csrf = [Depends(csrf_protect)]
app.include_router(auth.router, dependencies=_csrf)
app.include_router(dashboard.router, dependencies=_csrf)
app.include_router(events.router, dependencies=_csrf)
app.include_router(students.router, dependencies=_csrf)
app.include_router(houses.router, dependencies=_csrf)
app.include_router(certificates.router, dependencies=_csrf)
app.include_router(settings.router, dependencies=_csrf)
app.include_router(admins.router, dependencies=_csrf)
app.include_router(audit_log.router, dependencies=_csrf)
app.include_router(account.router, dependencies=_csrf)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (404, 403):
        return templates.TemplateResponse(request, "error.html", {
            "code": exc.status_code,
            "title": "Page not found" if exc.status_code == 404 else "Not allowed",
            "msg": (exc.detail if exc.status_code == 403 else "That page doesn't exist."),
        }, status_code=exc.status_code)
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(SyncError)
async def sync_error_handler(request: Request, exc: SyncError):
    # The change could NOT be written to the cloud database, so it was rolled back
    # (nothing was saved). Tell the admin so they can simply try again.
    return templates.TemplateResponse(request, "error.html", {
        "code": "!",
        "title": "Couldn't save — cloud database unreachable",
        "msg": "Your change was NOT saved. Check your connection and try again in a moment.",
    }, status_code=503)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return templates.TemplateResponse(request, "error.html", {
        "code": 500, "title": "Something went wrong",
        "msg": "An unexpected error occurred. Please try again.",
    }, status_code=500)

@app.on_event("startup")
async def startup_event():
    # Config sanity checks — warn loudly instead of failing silently.
    if not os.getenv("SECRET_KEY"):
        print("[config] WARNING: SECRET_KEY not set — using an insecure fallback. Set it in production.")
    if not (os.getenv("FIREBASE_KEY_JSON") or os.path.exists(
            os.getenv("FIREBASE_KEY", "key-period-473405-g2-firebase-adminsdk-fbsvc-2d943f120e.json"))):
        print("[config] WARNING: No Firebase credentials found — set FIREBASE_KEY_JSON (or FIREBASE_KEY).")
    if not COOKIE_SECURE:
        print("[config] NOTE: COOKIE_SECURE is off — set COOKIE_SECURE=true in production (HTTPS).")

    # Firestore is the source of truth. On every reboot we only PULL from it into
    # the local mirror — we never push local data up, so a restart can't overwrite
    # Firestore. Firestore only changes when an admin edits something in the app.
    try:
        loaded = hydrate_from_firestore()
        print(f"[firestore] hydrated {loaded} document(s) from Firestore into local mirror")
    except Exception as e:
        print("[firestore] hydrate failed (using existing local data):", e)
    init_db()

    # Real-time: listen for external/console edits and stream changes to browsers.
    try:
        realtime.start_listeners()
    except Exception as e:
        print("[realtime] could not start listeners (live updates disabled):", e)


@app.on_event("shutdown")
async def shutdown_event():
    try:
        realtime.stop_listeners()
    except Exception:
        pass


@app.get("/realtime/stream")
async def realtime_stream(request: Request):
    """Server-Sent Events: pushes a tick whenever the data changes so the browser
    can refresh. Auth required; only emits a counter, never data."""
    from routers.auth import verify_token
    if not verify_token(request):
        return Response(status_code=401)

    async def gen():
        last = live.get_version()
        yield "retry: 3000\n\n"           # tell EventSource to reconnect after 3s
        yield f"data: {last}\n\n"          # initial (browser ignores the first)
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            cur = live.get_version()
            if cur != last:
                last = cur
                idle = 0
                yield f"data: {cur}\n\n"
            else:
                idle += 1
                if idle >= 30:             # ~15s heartbeat keeps proxies from closing
                    idle = 0
                    yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/term-status-banner", response_class=HTMLResponse)
async def term_status_banner(request: Request, db=Depends(get_db)):
    """Polled by admin pages so a super-admin lock/unlock shows up live (~15s)."""
    from terms import term_state
    from routers.auth import verify_token
    from models.models import Admin
    email = verify_token(request)
    if not email:
        return HTMLResponse("")
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin or admin.role == "super_admin":
        return HTMLResponse("")  # super-admins manage terms; no banner for them
    state, _ = term_state(db)
    if state == "active":
        return HTMLResponse("")
    if state == "locked":
        title, msg = "Term locked", "This term is locked by the super admin. You can view data, but changes are disabled."
    else:
        title, msg = "No active term", "Ask your super admin to start or unlock a term — changes are disabled."
    return HTMLResponse(
        '<div class="toast toast-warn mb-5">'
        '<svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" class="shrink-0">'
        '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
        f'<div><b>{title}.</b> {msg}</div></div>'
    )
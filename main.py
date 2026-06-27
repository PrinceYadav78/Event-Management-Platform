from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from database import engine, Base, get_db
from models import models
from routers import events, students, houses, certificates, auth, dashboard, settings, admins, audit_log, account
from init_db import init_db
# Importing firestore_sync registers the SQLAlchemy commit hooks that push each
# individual change to Firestore in the background (see firestore_sync.py).
from firestore_sync import hydrate_from_firestore

Base.metadata.create_all(bind=engine)

app = FastAPI(title="National Public School - Events Manager")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(events.router)
app.include_router(students.router)
app.include_router(houses.router)
app.include_router(certificates.router)
app.include_router(settings.router)
app.include_router(admins.router)
app.include_router(audit_log.router)
app.include_router(account.router)

@app.on_event("startup")
async def startup_event():
    # Firestore is the source of truth. On every reboot we only PULL from it into
    # the local mirror — we never push local data up, so a restart can't overwrite
    # Firestore. Firestore only changes when an admin edits something in the app.
    try:
        loaded = hydrate_from_firestore()
        print(f"[firestore] hydrated {loaded} document(s) from Firestore into local mirror")
    except Exception as e:
        print("[firestore] hydrate failed (using existing local data):", e)
    init_db()

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
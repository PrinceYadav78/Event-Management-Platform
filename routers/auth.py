from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models.models import Admin
from jose import jwt
from datetime import datetime, timedelta
import bcrypt
import hashlib
import os
from dotenv import load_dotenv
from templating import templates

load_dotenv()

router = APIRouter()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key-do-not-use-in-prod")
ALGORITHM = "HS256"
# Set COOKIE_SECURE=true in production (HTTPS). Leave false for local http dev.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def pw_version(password_hash: str) -> str:
    """Short fingerprint of the password hash — changing the password rotates it,
    which invalidates any token carrying the old value."""
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:16]


def create_token(email: str, role: str = "admin", name: str = None, pv: str = None):
    expire = datetime.utcnow() + timedelta(hours=8)
    return jwt.encode(
        {"sub": email, "role": role, "name": name, "pv": pv, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM,
    )


def _resolve_token(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None
    email = payload.get("sub")
    if not email:
        return None
    # Validate against the live account so a password change logs old sessions out.
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).first()
    finally:
        db.close()
    if not admin:
        return None
    pv = payload.get("pv")
    if pv is not None and pw_version(admin.password_hash) != pv:
        return None
    return email


def verify_token(request: Request):
    """Resolve the logged-in admin's email, cached per-request (this is called
    several times per request — route guard, helpers, audit log)."""
    try:
        return request.state._auth_email  # cached for this request
    except AttributeError:
        pass
    result = _resolve_token(request)
    try:
        request.state._auth_email = result
    except Exception:
        pass
    return result


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))


def _set_auth_cookie(response, admin):
    response.set_cookie(
        "access_token",
        create_token(admin.email, admin.role, admin.name, pw_version(admin.password_hash)),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {})


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(request, "admin/login.html", {
            "error": "Invalid email or password"})
    response = RedirectResponse(url="/dashboard", status_code=303)
    _set_auth_cookie(response, admin)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token", samesite="lax", secure=COOKIE_SECURE)
    return response

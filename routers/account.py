"""Account screen — any logged-in admin can change their own password."""
import bcrypt
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models.models import Admin
from routers.auth import verify_token, verify_password, _set_auth_cookie
from templating import templates
from audit import log_action

router = APIRouter()


def _current_admin(request: Request, db: Session):
    email = verify_token(request)
    if not email:
        return None
    return db.query(Admin).filter(Admin.email == email).first()


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, db: Session = Depends(get_db)):
    admin = _current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "admin/account.html", {
        "active": "account",
        "admin": admin,
        "msg": request.query_params.get("msg"),
    })


@router.post("/account/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = _current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    if not verify_password(current_password, admin.password_hash):
        return RedirectResponse(url="/account?msg=wrong_current", status_code=303)
    if len(new_password) < 6:
        return RedirectResponse(url="/account?msg=too_short", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse(url="/account?msg=mismatch", status_code=303)
    admin.password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.commit()
    log_action(db, request, "Changed password", admin.email)
    # Re-issue this user's cookie with the new password fingerprint so they stay
    # logged in (the change invalidates every OTHER existing session for them).
    response = RedirectResponse(url="/account?msg=changed", status_code=303)
    _set_auth_cookie(response, admin)
    return response

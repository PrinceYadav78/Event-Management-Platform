"""Super-admin only: a filterable audit trail of admin actions, with undo."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models.models import AuditLog, Admin
from routers.auth import verify_token
from audit import undo_action, log_action
from templating import templates

router = APIRouter()


def _require_super(request: Request, db: Session):
    email = verify_token(request)
    if not email:
        return None
    admin = db.query(Admin).filter(Admin.email == email).first()
    return admin if (admin and admin.role == "super_admin") else None


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(500).all()
    total = db.query(AuditLog).count()
    return templates.TemplateResponse(request, "admin/audit.html", {
        "active": "audit",
        "logs": logs,
        "total": total,
    })


@router.post("/audit/undo/{log_id}")
async def audit_undo(log_id: str, request: Request, db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if not log:
        return RedirectResponse(url="/audit?msg=notfound", status_code=303)
    result = undo_action(db, log)
    if result == "ok":
        log_action(db, request, "Undid action", f"{log.action}: {log.detail or ''}".strip(": "))
    return RedirectResponse(url=f"/audit?msg={result}", status_code=303)

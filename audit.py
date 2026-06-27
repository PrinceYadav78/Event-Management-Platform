"""Audit logging — record which admin did what.

`log_action` is best-effort: a logging failure must never break the user's
actual request, so it swallows errors. It commits its own row (after the caller
has already committed the real change), which also syncs the entry to Firestore.
"""
from sqlalchemy.orm import Session

from models.models import Admin, AuditLog
from routers.auth import verify_token


def log_action(db: Session, request, action: str, detail: str = ""):
    try:
        email = verify_token(request)
        admin = db.query(Admin).filter(Admin.email == email).first() if email else None
        db.add(AuditLog(
            admin_email=email,
            admin_name=(admin.name if admin and admin.name else email),
            action=action,
            detail=detail or "",
        ))
        db.commit()
    except Exception as e:
        print("[audit] failed to log:", e)
        try:
            db.rollback()
        except Exception:
            pass

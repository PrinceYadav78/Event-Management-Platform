from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import SchoolClass, TermSettings, Student, House, Admin, AppConfig
from models.models import get_grade_group
from routers.auth import verify_token
from appconfig import get_config
from datetime import datetime
import csv
import io
import re

YEAR_RE = re.compile(r"\d{4}-\d{2}")

router = APIRouter()
from templating import templates
from audit import log_action, snapshot_class

from terms import is_term_locked, get_active_term, default_academic_year

def require_super_admin(request: Request, db: Session):
    """Return the Admin row only if the caller is a logged-in super_admin."""
    email = verify_token(request)
    if not email:
        return None
    admin = db.query(Admin).filter(Admin.email == email).first()
    return admin if (admin and admin.role == "super_admin") else None

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    classes = db.query(SchoolClass).order_by(SchoolClass.class_name).all()
    terms = db.query(TermSettings).order_by(TermSettings.created_at.desc()).all()
    return templates.TemplateResponse(request, "admin/settings.html", {
        "classes": classes,
        "terms": terms,
        "active_term": get_active_term(db),
        "app_config": get_config(db),
        "active": "settings"
    })

@router.post("/settings/permissions")
async def update_permissions(request: Request, teachers_can_delete: str = Form(None), db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    cfg = db.query(AppConfig).first()
    if cfg:
        cfg.teachers_can_delete = (teachers_can_delete == "on")
        db.commit()
        log_action(db, request, "Updated permissions", f"teachers_can_delete={cfg.teachers_can_delete}")
    return RedirectResponse(url="/settings?msg=perms_saved", status_code=303)

@router.post("/settings/classes/add")
async def add_class(
    request: Request,
    grade: str = Form(...),
    section: str = Form(...),
    grade_group: str = Form(None),
    db: Session = Depends(get_db)
):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    class_name = f"{grade.strip()} {section.strip()}".strip()
    existing = db.query(SchoolClass).filter(SchoolClass.class_name == class_name).first()
    if grade and section and not existing:
        group = grade_group if grade_group in ("Primary", "Middle", "Senior") else get_grade_group(class_name)
        db.add(SchoolClass(class_name=class_name, grade_group=group))
        db.commit()
        log_action(db, request, "Added class", class_name)
    return RedirectResponse(url="/settings", status_code=303)

@router.post("/settings/classes/delete/{class_id}")
async def delete_class(
    class_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    school_class = db.query(SchoolClass).filter(
        SchoolClass.id == class_id
    ).first()
    if school_class:
        _cn = school_class.class_name
        snap = snapshot_class(school_class)
        db.delete(school_class)
        db.commit()
        log_action(db, request, "Deleted class", _cn,
                   undo_type="class", undo_data=snap)
    return RedirectResponse(url="/settings", status_code=303)

@router.post("/settings/term/create")
async def create_term(
    request: Request,
    term_name: str = Form(...),
    academic_year: str = Form(None),
    db: Session = Depends(get_db),
):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    ay = (academic_year or "").strip()
    if ay and not YEAR_RE.fullmatch(ay):
        return RedirectResponse(url="/settings?msg=bad_year", status_code=303)
    for t in db.query(TermSettings).all():
        t.is_active = False
    new_term = TermSettings(
        term_name=term_name.strip(),
        academic_year=(ay if ay else default_academic_year()),
        is_active=True,
        is_locked=False,
    )
    db.add(new_term)
    db.commit()
    log_action(db, request, "Created term", f"{new_term.term_name} ({new_term.academic_year})")
    return RedirectResponse(url="/settings?msg=term_created", status_code=303)

@router.post("/settings/term/edit/{term_id}")
async def edit_term(
    term_id: str,
    request: Request,
    term_name: str = Form(...),
    academic_year: str = Form(None),
    db: Session = Depends(get_db),
):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    ay = (academic_year or "").strip()
    if ay and not YEAR_RE.fullmatch(ay):
        return RedirectResponse(url="/settings?msg=bad_year", status_code=303)
    term = db.query(TermSettings).filter(TermSettings.id == term_id).first()
    if term:
        if term_name.strip():
            term.term_name = term_name.strip()
        term.academic_year = ay if ay else None
        db.commit()
        log_action(db, request, "Edited term", f"{term.term_name} ({term.academic_year})")
    return RedirectResponse(url="/settings?msg=term_updated", status_code=303)

@router.post("/settings/term/activate/{term_id}")
async def activate_term(term_id: str, request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    target = db.query(TermSettings).filter(TermSettings.id == term_id).first()
    if target:
        for t in db.query(TermSettings).all():
            t.is_active = (t.id == term_id)
        db.commit()
        log_action(db, request, "Switched active term", f"{target.term_name} ({target.academic_year})")
    return RedirectResponse(url="/settings?msg=term_activated", status_code=303)

@router.post("/settings/term/lock/{term_id}")
async def lock_term(term_id: str, request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    term = db.query(TermSettings).filter(TermSettings.id == term_id).first()
    if term:
        term.is_locked = True
        term.locked_at = datetime.utcnow()
        db.commit()
        log_action(db, request, "Locked term", term.term_name)
    return RedirectResponse(url="/settings?msg=locked", status_code=303)

@router.post("/settings/term/unlock/{term_id}")
async def unlock_term(term_id: str, request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    term = db.query(TermSettings).filter(TermSettings.id == term_id).first()
    if term:
        term.is_locked = False
        term.locked_at = None
        db.commit()
        log_action(db, request, "Unlocked term", term.term_name)
    return RedirectResponse(url="/settings?msg=unlocked", status_code=303)

# Student CSV import/template moved to the Students page (routers/students.py).
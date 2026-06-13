from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import SchoolClass, TermSettings, Student, House
from models.models import get_grade_group
from routers.auth import verify_token
from datetime import datetime
import csv
import io

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def is_term_locked(db: Session) -> bool:
    term = db.query(TermSettings).first()
    return term.is_locked if term else False

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    classes = db.query(SchoolClass).order_by(SchoolClass.class_name).all()
    term = db.query(TermSettings).first()
    return templates.TemplateResponse(request, "admin/settings.html", {
        "classes": classes,
        "term": term,
        "active": "settings"
    })

@router.post("/settings/classes/add")
async def add_class(
    request: Request,
    class_name: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    existing = db.query(SchoolClass).filter(
        SchoolClass.class_name == class_name
    ).first()
    if not existing:
        grade_group = get_grade_group(class_name)
        new_class = SchoolClass(
            class_name=class_name,
            grade_group=grade_group
        )
        db.add(new_class)
        db.commit()
    return RedirectResponse(url="/settings", status_code=302)

@router.post("/settings/classes/delete/{class_id}")
async def delete_class(
    class_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    school_class = db.query(SchoolClass).filter(
        SchoolClass.id == class_id
    ).first()
    if school_class:
        db.delete(school_class)
        db.commit()
    return RedirectResponse(url="/settings", status_code=302)

@router.post("/settings/term/lock")
async def lock_term(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    term = db.query(TermSettings).first()
    if term:
        term.is_locked = True
        term.locked_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(url="/settings?msg=locked", status_code=302)

@router.post("/settings/term/unlock")
async def unlock_term(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    term = db.query(TermSettings).first()
    if term:
        term.is_locked = False
        term.locked_at = None
        db.commit()
    return RedirectResponse(url="/settings?msg=unlocked", status_code=302)

@router.post("/settings/term/rename")
async def rename_term(
    request: Request,
    term_name: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    term = db.query(TermSettings).first()
    if term:
        term.term_name = term_name
        db.commit()
    return RedirectResponse(url="/settings", status_code=302)

@router.get("/settings/students/template")
async def download_template(request: Request):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "roll_number", "class_name", "house_name"])
    writer.writerow(["Arjun Sharma", "2024001", "VI A", "Nicon"])
    writer.writerow(["Priya Patel", "2024002", "IX B", "Maxims"])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_template.csv"}
    )

@router.post("/settings/students/import")
async def import_students(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    if is_term_locked(db):
        return RedirectResponse(url="/settings?msg=locked_error", status_code=302)
    form = await request.form()
    file = form.get("csv_file")
    if not file:
        return RedirectResponse(url="/settings?msg=no_file", status_code=302)
    contents = await file.read()
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    houses = {h.name.lower(): h for h in db.query(House).all()}
    added = 0
    skipped = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        try:
            name = row.get("name", "").strip()
            roll = row.get("roll_number", "").strip()
            class_name = row.get("class_name", "").strip()
            house_name = row.get("house_name", "").strip().lower()
            if not all([name, roll, class_name, house_name]):
                errors.append(f"Row {i}: missing fields")
                skipped += 1
                continue
            if house_name not in houses:
                errors.append(f"Row {i}: house '{house_name}' not found")
                skipped += 1
                continue
            existing = db.query(Student).filter(Student.roll_number == roll).first()
            if existing:
                skipped += 1
                continue
            student = Student(
                name=name,
                roll_number=roll,
                class_name=class_name,
                grade_group=get_grade_group(class_name),
                house_id=houses[house_name].id
            )
            db.add(student)
            added += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")
            skipped += 1
    db.commit()
    msg = f"import_done_{added}_{skipped}"
    return RedirectResponse(url=f"/settings?msg={msg}", status_code=302)
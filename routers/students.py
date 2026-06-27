from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import Student, House, SchoolClass
from models.models import get_grade_group
from routers.auth import verify_token
from models.models import Student, House, SchoolClass, TermSettings
import csv
import io

from terms import is_term_locked as is_locked

router = APIRouter()
from templating import templates
from audit import log_action

@router.get("/students", response_class=HTMLResponse)
async def students_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    students = db.query(Student).join(House).all()
    houses = db.query(House).all()
    classes = db.query(SchoolClass).order_by(SchoolClass.class_name).all()
    return templates.TemplateResponse(request, "admin/students.html", {
        "students": students,
        "houses": houses,
        "classes": classes,
        "active": "students"
    })

@router.post("/students/add")
async def add_student(
    request: Request,
    name: str = Form(...),
    roll_number: str = Form(...),
    class_name: str = Form(...),
    house_id: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    grade_group = get_grade_group(class_name)
    student = Student(
        name=name,
        roll_number=roll_number,
        class_name=class_name,
        grade_group=grade_group,
        house_id=house_id
    )
    db.add(student)
    db.commit()
    log_action(db, request, "Added student", f"{name} ({roll_number})")
    return RedirectResponse(url="/students", status_code=303)

@router.post("/students/delete/{student_id}")
async def delete_student(
    student_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    student = db.query(Student).filter(Student.id == student_id).first()
    if student:
        for p in student.participations:
            if p.points_awarded > 0:
                house = student.house
                if house:
                    house.total_points -= p.points_awarded
                    if student.grade_group == "Primary":
                        house.primary_points -= p.points_awarded
                    elif student.grade_group == "Middle":
                        house.middle_points -= p.points_awarded
                    elif student.grade_group == "Senior":
                        house.senior_points -= p.points_awarded
        _deleted_name = student.name
        db.delete(student)
        db.commit()
        log_action(db, request, "Deleted student", _deleted_name)
    return RedirectResponse(url="/students", status_code=303)

@router.post("/students/edit/{student_id}")
async def edit_student(
    student_id: str,
    request: Request,
    name: str = Form(...),
    roll_number: str = Form(...),
    class_name: str = Form(...),
    house_id: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    
    student = db.query(Student).filter(Student.id == student_id).first()
    if student:
        student.name = name
        student.roll_number = roll_number
        student.class_name = class_name
        student.house_id = house_id
        student.grade_group = get_grade_group(class_name)
        db.commit()

    return RedirectResponse(url="/students?msg=edited", status_code=303)


@router.get("/students/template")
async def students_template(request: Request):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "roll_number", "class_name", "house_name"])
    writer.writerow(["Arjun Sharma", "2024001", "VI A", "Nicon"])
    writer.writerow(["Priya Patel", "2024002", "IX B", "Maxims"])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_template.csv"},
    )


@router.post("/students/import")
async def import_students(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    form = await request.form()
    file = form.get("csv_file")
    if not file:
        return RedirectResponse(url="/students?msg=no_file", status_code=303)
    contents = await file.read()
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    houses = {h.name.lower(): h for h in db.query(House).all()}
    added = 0
    skipped = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        roll = (row.get("roll_number") or "").strip()
        class_name = (row.get("class_name") or "").strip()
        house_name = (row.get("house_name") or "").strip().lower()
        if not all([name, roll, class_name, house_name]) or house_name not in houses:
            skipped += 1
            continue
        if db.query(Student).filter(Student.roll_number == roll).first():
            skipped += 1
            continue
        db.add(Student(
            name=name,
            roll_number=roll,
            class_name=class_name,
            grade_group=get_grade_group(class_name),
            house_id=houses[house_name].id,
        ))
        added += 1
    db.commit()
    log_action(db, request, "Imported students", f"{added} added, {skipped} skipped")
    return RedirectResponse(url=f"/students?msg=import_done_{added}_{skipped}", status_code=303)
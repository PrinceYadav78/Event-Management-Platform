from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from models.models import Student, House, SchoolClass, Admin
from models.models import get_grade_group
from routers.auth import verify_token
import csv
import io

from terms import is_term_locked as is_locked
from appconfig import teachers_can_delete

router = APIRouter()
from templating import templates
from audit import log_action, snapshot_student

PER_PAGE = 50


def _bucket(house, grade, delta):
    if grade == "Primary":
        house.primary_points += delta
    elif grade == "Middle":
        house.middle_points += delta
    elif grade == "Senior":
        house.senior_points += delta


def _can_delete(request: Request, db: Session) -> bool:
    email = verify_token(request)
    admin = db.query(Admin).filter(Admin.email == email).first() if email else None
    if not admin:
        return False
    return admin.role == "super_admin" or teachers_can_delete(db)


@router.get("/students", response_class=HTMLResponse)
async def students_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)

    q = (request.query_params.get("q") or "").strip()
    f_house = (request.query_params.get("house") or "").strip()
    f_grade = (request.query_params.get("grade") or "").strip()
    sort = (request.query_params.get("sort") or "name").strip()
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1

    query = db.query(Student).join(House)
    if q:
        like = f"%{q}%"
        query = query.filter(Student.name.ilike(like) | Student.roll_number.ilike(like) | Student.class_name.ilike(like))
    if f_house:
        query = query.filter(House.name == f_house)
    if f_grade in ("Primary", "Middle", "Senior"):
        query = query.filter(Student.grade_group == f_grade)

    if sort == "name-desc":
        query = query.order_by(Student.name.desc())
    elif sort == "roll":
        query = query.order_by(Student.roll_number.asc())
    elif sort == "house":
        query = query.order_by(House.name.asc(), Student.name.asc())
    elif sort == "class":
        query = query.order_by(Student.class_name.asc(), Student.name.asc())
    else:
        query = query.order_by(Student.name.asc())

    total = query.count()
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)
    students = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()

    return templates.TemplateResponse(request, "admin/students.html", {
        "students": students,
        "houses": db.query(House).all(),
        "classes": db.query(SchoolClass).order_by(SchoolClass.class_name).all(),
        "active": "students",
        "page": page, "pages": pages, "total": total,
        "total_all": db.query(Student).count(),
        "primary_count": db.query(Student).filter(Student.grade_group == "Primary").count(),
        "middle_count": db.query(Student).filter(Student.grade_group == "Middle").count(),
        "senior_count": db.query(Student).filter(Student.grade_group == "Senior").count(),
        "q": q, "f_house": f_house, "f_grade": f_grade, "sort": sort,
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
    roll_number = roll_number.strip()
    if db.query(Student).filter(Student.roll_number == roll_number).first():
        return RedirectResponse(url="/students?msg=dup_roll", status_code=303)
    db.add(Student(
        name=name, roll_number=roll_number, class_name=class_name,
        grade_group=get_grade_group(class_name), house_id=house_id,
    ))
    db.commit()
    log_action(db, request, "Added student", f"{name} ({roll_number})")
    return RedirectResponse(url="/students?msg=added", status_code=303)


@router.post("/students/delete/{student_id}")
async def delete_student(student_id: str, request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=303)
    if not _can_delete(request, db):
        return RedirectResponse(url="/students?msg=no_delete", status_code=303)
    student = db.query(Student).filter(Student.id == student_id).first()
    if student:
        snap = snapshot_student(student)
        for p in student.participations:
            if p.points_awarded and p.points_awarded > 0 and student.house:
                student.house.total_points -= p.points_awarded
                _bucket(student.house, student.grade_group, -p.points_awarded)
        _deleted_name = student.name
        db.delete(student)
        db.commit()
        log_action(db, request, "Deleted student", _deleted_name,
                   undo_type="student", undo_data=snap)
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
    roll_number = roll_number.strip()
    student = db.query(Student).filter(Student.id == student_id).first()
    if student:
        if db.query(Student).filter(Student.roll_number == roll_number, Student.id != student_id).first():
            return RedirectResponse(url="/students?msg=dup_roll", status_code=303)
        # Move any points this student earned to the new house / grade bucket.
        total_pts = sum((p.points_awarded or 0) for p in student.participations)
        old_house, old_grade = student.house, student.grade_group
        new_grade = get_grade_group(class_name)
        if total_pts and old_house:
            old_house.total_points -= total_pts
            _bucket(old_house, old_grade, -total_pts)
        student.name = name
        student.roll_number = roll_number
        student.class_name = class_name
        student.house_id = house_id
        student.grade_group = new_grade
        if total_pts:
            new_house = db.query(House).filter(House.id == house_id).first()
            if new_house:
                new_house.total_points += total_pts
                _bucket(new_house, new_grade, total_pts)
        db.commit()
        log_action(db, request, "Edited student", student.name)
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
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = contents.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    houses = {h.name.lower(): h for h in db.query(House).all()}
    existing_rolls = {r[0] for r in db.query(Student.roll_number).all()}
    added = 0
    skipped = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        roll = (row.get("roll_number") or "").strip()
        class_name = (row.get("class_name") or "").strip()
        house_name = (row.get("house_name") or "").strip().lower()
        if not all([name, roll, class_name, house_name]) or house_name not in houses or roll in existing_rolls:
            skipped += 1
            continue
        existing_rolls.add(roll)
        db.add(Student(
            name=name, roll_number=roll, class_name=class_name,
            grade_group=get_grade_group(class_name), house_id=houses[house_name].id,
        ))
        added += 1
    db.commit()
    log_action(db, request, "Imported students", f"{added} added, {skipped} skipped")
    return RedirectResponse(url=f"/students?msg=import_done_{added}_{skipped}", status_code=303)

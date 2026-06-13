from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import Student, House, SchoolClass
from models.models import get_grade_group
from routers.auth import verify_token
from models.models import Student, House, SchoolClass, TermSettings

def is_locked(db):
    term = db.query(TermSettings).first()
    return term.is_locked if term else False

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/students", response_class=HTMLResponse)
async def students_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=302)
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
        return RedirectResponse(url="/login")
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=302)
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
    return RedirectResponse(url="/students", status_code=302)

@router.post("/students/delete/{student_id}")
async def delete_student(
    student_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    if is_locked(db):
        return RedirectResponse(url="/students?msg=locked", status_code=302)
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
        db.delete(student)
        db.commit()
    return RedirectResponse(url="/students", status_code=302)
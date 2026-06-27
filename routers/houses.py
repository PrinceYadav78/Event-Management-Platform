from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import House, PointsConfig, Admin, Student
from routers.auth import verify_token, verify_password

router = APIRouter()
from templating import templates
from audit import log_action

@router.get("/houses", response_class=HTMLResponse)
async def houses_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    houses = db.query(House).all()
    points_config = db.query(PointsConfig).order_by(PointsConfig.position).all()
    return templates.TemplateResponse(request, "admin/houses.html", {
        "houses": houses,
        "points_config": points_config
    })

def _require_super(request: Request, db: Session):
    email = verify_token(request)
    if not email:
        return None
    admin = db.query(Admin).filter(Admin.email == email).first()
    return admin if (admin and admin.role == "super_admin") else None


@router.get("/houses/manage", response_class=HTMLResponse)
async def manage_houses(request: Request, db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    houses = db.query(House).order_by(House.name).all()
    counts = {h.id: db.query(Student).filter(Student.house_id == h.id).count() for h in houses}
    return templates.TemplateResponse(request, "admin/manage_houses.html", {
        "active": "houses", "houses": houses, "counts": counts,
        "msg": request.query_params.get("msg"),
    })


@router.post("/houses/manage/add")
async def add_house(request: Request, name: str = Form(...), color: str = Form("#2563eb"), db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    name = name.strip()
    if name and not db.query(House).filter(House.name == name).first():
        db.add(House(name=name, color=color, total_points=0, primary_points=0, middle_points=0, senior_points=0))
        db.commit()
        log_action(db, request, "Created house", f"{name} ({color})")
    return RedirectResponse(url="/houses/manage?msg=added", status_code=303)


@router.post("/houses/manage/edit/{house_id}")
async def edit_house(house_id: str, request: Request, name: str = Form(...), color: str = Form(...), db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    house = db.query(House).filter(House.id == house_id).first()
    if house and name.strip():
        house.name = name.strip()
        house.color = color
        db.commit()
        log_action(db, request, "Edited house", f"{house.name} ({color})")
    return RedirectResponse(url="/houses/manage?msg=updated", status_code=303)


@router.post("/houses/manage/delete/{house_id}")
async def delete_house(house_id: str, request: Request, db: Session = Depends(get_db)):
    if not _require_super(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    house = db.query(House).filter(House.id == house_id).first()
    if house:
        if db.query(Student).filter(Student.house_id == house_id).count() > 0:
            return RedirectResponse(url="/houses/manage?msg=has_students", status_code=303)
        _name = house.name
        db.delete(house)
        db.commit()
        log_action(db, request, "Deleted house", _name)
    return RedirectResponse(url="/houses/manage?msg=deleted", status_code=303)


@router.post("/houses/points/update")
async def update_points(
    request: Request,
    db: Session = Depends(get_db)
):
    email = verify_token(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)
    # Points configuration is super-admin only.
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin or admin.role != "super_admin":
        return RedirectResponse(url="/houses", status_code=303)
    form = await request.form()
    configs = db.query(PointsConfig).all()
    for config in configs:
        key = f"points_{config.position}"
        if key in form:
            config.points = int(form[key])
    save_default = form.get("save_default") == "on"
    if save_default:
        for config in configs:
            config.is_default = True
    db.commit()
    log_action(db, request, "Updated points config", "")
    return RedirectResponse(url="/houses", status_code=303)

@router.post("/houses/reset")
async def reset_points(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    email = verify_token(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)
    admin = db.query(Admin).filter(Admin.email == email).first()
    # Only the super admin may reset points...
    if not admin or admin.role != "super_admin":
        return RedirectResponse(url="/houses?reset_error=forbidden", status_code=303)
    # ...and they must re-enter their login password.
    if not verify_password(password, admin.password_hash):
        return RedirectResponse(url="/houses?reset_error=badpass", status_code=303)
    houses = db.query(House).all()
    for house in houses:
        house.total_points = 0
        house.primary_points = 0
        house.middle_points = 0
        house.senior_points = 0
    db.commit()
    log_action(db, request, "Reset all points", "All house points set to zero")
    return RedirectResponse(url="/houses?msg=reset_done", status_code=303)
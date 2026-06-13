from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import House, PointsConfig
from app.routers.auth import verify_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/houses", response_class=HTMLResponse)
async def houses_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    houses = db.query(House).all()
    points_config = db.query(PointsConfig).order_by(PointsConfig.position).all()
    return templates.TemplateResponse(request, "admin/houses.html", {
        "houses": houses,
        "points_config": points_config
    })

@router.post("/houses/points/update")
async def update_points(
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login")
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
    return RedirectResponse(url="/houses", status_code=302)

@router.post("/houses/reset")
async def reset_points(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    houses = db.query(House).all()
    for house in houses:
        house.total_points = 0
        house.primary_points = 0
        house.middle_points = 0
        house.senior_points = 0
    db.commit()
    return RedirectResponse(url="/houses", status_code=302)
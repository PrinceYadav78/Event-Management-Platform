from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import House, Student, Event, CertificateTemplate
from routers.auth import verify_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login")
    houses = db.query(House).order_by(House.total_points.desc()).all()
    total_students = db.query(Student).count()
    total_events = db.query(Event).count()
    completed_events = db.query(Event).filter(Event.is_completed == True).count()
    total_certificates = db.query(CertificateTemplate).count()
    recent_events = db.query(Event).order_by(Event.event_date.desc()).limit(5).all()
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "houses": houses,
        "total_students": total_students,
        "total_events": total_events,
        "completed_events": completed_events,
        "total_certificates": total_certificates,
        "recent_events": recent_events,
        "active": "dashboard"
    })
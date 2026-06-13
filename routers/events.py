from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import Event, EventParticipant, Student, House, PointsConfig
from routers.auth import verify_token
from models.models import Event, EventParticipant, Student, House, PointsConfig, TermSettings
from models.models import Event, EventParticipant, Student, House, PointsConfig, TermSettings, Admin
def is_locked(db):
    term = db.query(TermSettings).first()
    return term.is_locked if term else False

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    events = db.query(Event).order_by(Event.event_date.desc()).all()
    return templates.TemplateResponse(request, "admin/events.html", {
        "events": events
    })

@router.post("/events/add")
async def add_event(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    event_date: str = Form(...),
    event_type: str = Form(...),
    grade_group: str = Form(...),
    status: str = Form("upcoming"),
    description: str = Form(""),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    from datetime import date
    event = Event(
        name=name,
        category=category,
        event_date=date.fromisoformat(event_date),
        event_type=event_type,
        grade_group=grade_group,
        status=status,
        is_completed=(status == "completed"),
        description=description
    )
    db.add(event)
    db.commit()
    return RedirectResponse(url="/events", status_code=303)

@router.get("/events/{event_id}", response_class=HTMLResponse)
async def event_detail(event_id: str, request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    event = db.query(Event).filter(Event.id == event_id).first()
    participants = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id
    ).all()
    students = db.query(Student).filter(
        Student.grade_group == event.grade_group
    ).all()
    participated_ids = [p.student_id for p in participants]
    return templates.TemplateResponse(request, "admin/event_detail.html", {
        "event": event,
        "participants": participants,
        "students": students,
        "participated_ids": participated_ids
    })

@router.post("/events/{event_id}/add_participant")
async def add_participant(
    event_id: str,
    request: Request,
    student_id: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    existing = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id,
        EventParticipant.student_id == student_id
    ).first()
    if not existing:
        participant = EventParticipant(
            event_id=event_id,
            student_id=student_id
        )
        db.add(participant)
        db.commit()
    return RedirectResponse(url=f"/events/{event_id}", status_code=303)

@router.post("/events/{event_id}/record_results")
async def record_results(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    form = await request.form()
    event = db.query(Event).filter(Event.id == event_id).first()
    participants = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id
    ).all()
    points_config = {p.position: p.points for p in db.query(PointsConfig).all()}

    for participant in participants:
        key = f"position_{participant.id}"
        if key in form and form[key]:
            position = int(form[key])
            participant.position = position
            pts = points_config.get(position, points_config.get(0, 1))
            old_points = participant.points_awarded
            participant.points_awarded = pts

            house = db.query(House).filter(
                House.id == participant.student.house_id
            ).first()
            if house:
                diff = pts - old_points
                house.total_points += diff
                grade_group = participant.student.grade_group
                if grade_group == "Primary":
                    house.primary_points += diff
                elif grade_group == "Middle":
                    house.middle_points += diff
                elif grade_group == "Senior":
                    house.senior_points += diff

    event.is_completed = True
    db.commit()
    return RedirectResponse(url=f"/events/{event_id}", status_code=303)

@router.post("/events/delete/{event_id}")
async def delete_event(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        for p in event.participants:
            if p.points_awarded > 0:
                house = db.query(House).filter(House.id == p.student.house_id).first()
                if house:
                    house.total_points -= p.points_awarded
                    if p.student.grade_group == "Primary":
                        house.primary_points -= p.points_awarded
                    elif p.student.grade_group == "Middle":
                        house.middle_points -= p.points_awarded
                    elif p.student.grade_group == "Senior":
                        house.senior_points -= p.points_awarded
        db.delete(event)
        db.commit()
    return RedirectResponse(url="/events", status_code=303)
@router.post("/events/edit/{event_id}")
async def edit_event(
    event_id: str,
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    event_date: str = Form(...),
    event_type: str = Form(...),
    grade_group: str = Form(...),
    status: str = Form("upcoming"),
    description: str = Form(""),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    from datetime import date
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        event.name = name
        event.category = category
        event.event_date = date.fromisoformat(event_date)
        event.event_type = event_type
        event.grade_group = grade_group
        event.status = status
        event.is_completed = (status == "completed")
        event.description = description
        db.commit()
    return RedirectResponse(url="/events?msg=edited", status_code=303)
@router.post("/events/{event_id}/verify_admin")
async def verify_admin(
    event_id: str,
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    email = verify_token(request)
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin:
        return RedirectResponse(url=f"/events/{event_id}?unlock_error=1", status_code=303)
    import bcrypt
    if not bcrypt.checkpw(password.encode("utf-8"), admin.password_hash.encode("utf-8")):
        return RedirectResponse(url=f"/events/{event_id}?unlock_error=1", status_code=303)
    return RedirectResponse(url=f"/events/{event_id}?edit_results=1", status_code=303)

@router.post("/events/{event_id}/edit_results")
async def edit_results(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url=f"/events/{event_id}?msg=locked", status_code=303)
    form = await request.form()
    event = db.query(Event).filter(Event.id == event_id).first()
    participants = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id
    ).all()
    points_config = {p.position: p.points for p in db.query(PointsConfig).all()}
    for participant in participants:
        key = f"position_{participant.id}"
        if key in form:
            new_position = int(form[key]) if form[key] else 0
            new_pts = points_config.get(new_position, points_config.get(0, 1))
            old_pts = participant.points_awarded
            if new_pts != old_pts:
                house = db.query(House).filter(
                    House.id == participant.student.house_id
                ).first()
                if house:
                    diff = new_pts - old_pts
                    house.total_points += diff
                    grade_group = participant.student.grade_group
                    if grade_group == "Primary":
                        house.primary_points += diff
                    elif grade_group == "Middle":
                        house.middle_points += diff
                    elif grade_group == "Senior":
                        house.senior_points += diff
            participant.position = new_position if new_position else None
            participant.points_awarded = new_pts
    db.commit()
    return RedirectResponse(url=f"/events/{event_id}?msg=results_updated", status_code=303)
@router.post("/events/bulk/form")
async def bulk_add_events_form(
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    form = await request.form()
    added = 0
    from datetime import date
    for i in range(10):
        name = form.get(f"name_{i}", "").strip()
        event_date = form.get(f"date_{i}", "").strip()
        if not name or not event_date:
            continue
        try:
            event = Event(
                name=name,
                category=form.get(f"category_{i}", "Sports"),
                event_date=date.fromisoformat(event_date),
                event_type=form.get(f"type_{i}", "individual"),
                grade_group=form.get(f"grade_{i}", "Primary"),
                description=""
            )
            db.add(event)
            added += 1
        except Exception:
            continue
    db.commit()
    return RedirectResponse(url=f"/events?msg=bulk_added_{added}", status_code=303)

@router.post("/events/bulk/csv")
async def bulk_add_events_csv(
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_locked(db):
        return RedirectResponse(url="/events?msg=locked", status_code=303)
    import csv, io
    form = await request.form()
    file = form.get("events_csv")
    if not file:
        return RedirectResponse(url="/events?msg=no_file", status_code=303)
    contents = await file.read()
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    added = 0
    skipped = 0
    from datetime import date
    for row in reader:
        try:
            name = row.get("name", "").strip()
            event_date = row.get("date", "").strip()
            if not name or not event_date:
                skipped += 1
                continue
            event = Event(
                name=name,
                category=row.get("category", "Sports").strip(),
                event_date=date.fromisoformat(event_date),
                event_type=row.get("type", "individual").strip(),
                grade_group=row.get("grade_group", "Primary").strip(),
                description=row.get("description", "").strip()
            )
            db.add(event)
            added += 1
        except Exception:
            skipped += 1
    db.commit()
    return RedirectResponse(url=f"/events?msg=bulk_added_{added}", status_code=303)

@router.get("/events/bulk/template")
async def download_events_template(request: Request):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "date", "category", "grade_group", "type", "description"])
    writer.writerow(["100m Sprint", "2025-06-10", "Sports", "Primary", "individual", "Annual sports day"])
    writer.writerow(["Science Quiz", "2025-06-11", "Academic", "Middle", "individual", "Inter-house quiz"])
    writer.writerow(["Group Dance", "2025-06-12", "Cultural", "Senior", "team", "Cultural fest"])
    output.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events_template.csv"}
    )

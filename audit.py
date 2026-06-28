"""Audit logging — record which admin did what, and let a super-admin undo
reversible (deletion) actions by restoring a JSON snapshot taken at delete time.

`log_action` is best-effort: a logging failure must never break the user's
actual request, so it swallows errors. It commits its own row (after the caller
has already committed the real change), which also syncs the entry to Firestore.
"""
import json
from datetime import date

from sqlalchemy.orm import Session

from models.models import (Admin, AuditLog, Student, Event, EventParticipant,
                           House, SchoolClass)
from routers.auth import verify_token


def log_action(db: Session, request, action: str, detail: str = "",
               undo_type: str = None, undo_data=None):
    try:
        email = verify_token(request)
        admin = db.query(Admin).filter(Admin.email == email).first() if email else None
        db.add(AuditLog(
            admin_email=email,
            admin_name=(admin.name if admin and admin.name else email),
            action=action,
            detail=detail or "",
            undo_type=undo_type,
            undo_data=json.dumps(undo_data) if undo_data is not None else None,
        ))
        db.commit()
    except Exception as e:
        print("[audit] failed to log:", e)
        try:
            db.rollback()
        except Exception:
            pass


# ---- snapshot builders (called right before a delete) ----

def snapshot_student(student) -> dict:
    return {
        "id": student.id, "name": student.name, "roll_number": student.roll_number,
        "class_name": student.class_name, "grade_group": student.grade_group,
        "house_id": student.house_id,
        "participations": [
            {"id": p.id, "event_id": p.event_id, "position": p.position,
             "points_awarded": p.points_awarded or 0}
            for p in student.participations
        ],
    }


def snapshot_event(event) -> dict:
    return {
        "id": event.id, "name": event.name, "category": event.category,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "event_type": event.event_type, "grade_group": event.grade_group,
        "status": event.status, "is_completed": bool(event.is_completed),
        "description": event.description,
        "participants": [
            {"id": p.id, "student_id": p.student_id, "position": p.position,
             "points_awarded": p.points_awarded or 0,
             "house_id": (p.student.house_id if p.student else None),
             "grade_group": (p.student.grade_group if p.student else None)}
            for p in event.participants
        ],
    }


def snapshot_house(house) -> dict:
    return {
        "id": house.id, "name": house.name, "color": house.color,
        "total_points": house.total_points, "primary_points": house.primary_points,
        "middle_points": house.middle_points, "senior_points": house.senior_points,
    }


def snapshot_class(sc) -> dict:
    return {"id": sc.id, "class_name": sc.class_name, "grade_group": sc.grade_group}


# ---- restore (undo) ----

def _apply_points(house, grade_group, delta):
    house.total_points = (house.total_points or 0) + delta
    if grade_group == "Primary":
        house.primary_points = (house.primary_points or 0) + delta
    elif grade_group == "Middle":
        house.middle_points = (house.middle_points or 0) + delta
    elif grade_group == "Senior":
        house.senior_points = (house.senior_points or 0) + delta


def undo_action(db: Session, log) -> str:
    """Restore a deleted record from its audit snapshot.
    Returns "ok", "already_undone", "exists", "unsupported", or "error"."""
    if log.undone:
        return "already_undone"
    if not log.undo_type or not log.undo_data:
        return "unsupported"
    try:
        data = json.loads(log.undo_data)
        t = log.undo_type

        if t == "student":
            if db.query(Student).filter(Student.id == data["id"]).first():
                return "exists"
            if db.query(Student).filter(Student.roll_number == data["roll_number"]).first():
                return "exists"
            db.add(Student(id=data["id"], name=data["name"], roll_number=data["roll_number"],
                           class_name=data["class_name"], grade_group=data["grade_group"],
                           house_id=data["house_id"]))
            house = db.query(House).filter(House.id == data["house_id"]).first()
            for p in data.get("participations", []):
                if not db.query(Event).filter(Event.id == p["event_id"]).first():
                    continue  # event no longer exists
                db.add(EventParticipant(id=p["id"], event_id=p["event_id"],
                                        student_id=data["id"], position=p["position"],
                                        points_awarded=p["points_awarded"]))
                if p["points_awarded"] and house:
                    _apply_points(house, data["grade_group"], p["points_awarded"])

        elif t == "event":
            if db.query(Event).filter(Event.id == data["id"]).first():
                return "exists"
            db.add(Event(id=data["id"], name=data["name"], category=data["category"],
                         event_date=date.fromisoformat(data["event_date"]) if data["event_date"] else None,
                         event_type=data["event_type"], grade_group=data["grade_group"],
                         status=data["status"], is_completed=data["is_completed"],
                         description=data["description"]))
            for p in data.get("participants", []):
                if not db.query(Student).filter(Student.id == p["student_id"]).first():
                    continue
                db.add(EventParticipant(id=p["id"], event_id=data["id"],
                                        student_id=p["student_id"], position=p["position"],
                                        points_awarded=p["points_awarded"]))
                if p["points_awarded"] and p.get("house_id"):
                    house = db.query(House).filter(House.id == p["house_id"]).first()
                    if house:
                        _apply_points(house, p.get("grade_group"), p["points_awarded"])

        elif t == "house":
            if db.query(House).filter(House.id == data["id"]).first():
                return "exists"
            db.add(House(id=data["id"], name=data["name"], color=data["color"],
                         total_points=data["total_points"], primary_points=data["primary_points"],
                         middle_points=data["middle_points"], senior_points=data["senior_points"]))

        elif t == "class":
            if db.query(SchoolClass).filter(SchoolClass.id == data["id"]).first():
                return "exists"
            if db.query(SchoolClass).filter(SchoolClass.class_name == data["class_name"]).first():
                return "exists"
            db.add(SchoolClass(id=data["id"], class_name=data["class_name"],
                               grade_group=data["grade_group"]))
        else:
            return "unsupported"

        log.undone = True
        db.commit()
        return "ok"
    except Exception as e:
        print("[audit] undo failed:", e)
        try:
            db.rollback()
        except Exception:
            pass
        return "error"

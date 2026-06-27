from database import SessionLocal
from models.models import House, PointsConfig, Admin, SchoolClass, TermSettings
from models.models import get_grade_group
from terms import default_academic_year
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

from sqlalchemy import text

def init_db():
    db = SessionLocal()
    try:
        try:
            db.execute(text("ALTER TABLE events ADD COLUMN status VARCHAR(20) DEFAULT 'upcoming'"))
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.execute(text("ALTER TABLE admins ADD COLUMN name VARCHAR(200)"))
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.execute(text("ALTER TABLE term_settings ADD COLUMN academic_year VARCHAR(20)"))
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.execute(text("ALTER TABLE term_settings ADD COLUMN is_active BOOLEAN DEFAULT 0"))
            db.commit()
        except Exception:
            db.rollback()
        if db.query(House).count() == 0:
            houses = [
                House(name="Nicon",    color="#2563eb", total_points=0, primary_points=0, middle_points=0, senior_points=0),
                House(name="Maxims",   color="#16a34a", total_points=0, primary_points=0, middle_points=0, senior_points=0),
                House(name="Pericles", color="#ca8a04", total_points=0, primary_points=0, middle_points=0, senior_points=0),
                House(name="Regulus",  color="#dc2626", total_points=0, primary_points=0, middle_points=0, senior_points=0),
            ]
            db.add_all(houses)
            db.commit()

        if db.query(PointsConfig).count() == 0:
            default_points = [
                PointsConfig(position=1, points=10, is_default=True, label="1st place"),
                PointsConfig(position=2, points=7,  is_default=True, label="2nd place"),
                PointsConfig(position=3, points=5,  is_default=True, label="3rd place"),
                PointsConfig(position=0, points=1,  is_default=True, label="Participation"),
            ]
            db.add_all(default_points)
            db.commit()

        if db.query(Admin).count() == 0:
            admin = Admin(
                email="admin@nps.com",
                name="Super Admin",
                password_hash=hash_password("admin123"),
                role="super_admin"
            )
            db.add(admin)
            db.commit()

        # Backfill a friendly name for any super-admin that lacks one.
        missing = db.query(Admin).filter(
            Admin.role == "super_admin",
            (Admin.name == None) | (Admin.name == "")  # noqa: E711
        ).all()
        if missing:
            for a in missing:
                a.name = "Super Admin"
            db.commit()

        if db.query(SchoolClass).count() == 0:
            classes = []
            sections_standard = ["A", "B", "C", "D", "E"]
            sections_senior = ["A", "B"]
            grades = [
                ("I",    sections_standard),
                ("II",   sections_standard),
                ("III",  sections_standard),
                ("IV",   sections_standard),
                ("V",    sections_standard),
                ("VI",   sections_standard),
                ("VII",  sections_standard),
                ("VIII", sections_standard),
                ("IX",   sections_standard),
                ("X",    sections_standard),
                ("XI",   sections_senior),
                ("XII",  sections_senior),
            ]
            for grade, sections in grades:
                for section in sections:
                    class_name = f"{grade} {section}"
                    classes.append(SchoolClass(
                        class_name=class_name,
                        grade_group=get_grade_group(class_name)
                    ))
            db.add_all(classes)
            db.commit()

        # Ensure there is a term, and exactly one active term (fixes term lock,
        # which previously did nothing because no term row existed).
        if db.query(TermSettings).count() == 0:
            db.add(TermSettings(term_name="Term 1", academic_year=default_academic_year(),
                                is_active=True, is_locked=False))
            db.commit()
        elif db.query(TermSettings).filter(TermSettings.is_active == True).count() == 0:  # noqa: E712
            t = db.query(TermSettings).first()
            t.is_active = True
            if not t.academic_year:
                t.academic_year = default_academic_year()
            db.commit()

    finally:
        db.close()
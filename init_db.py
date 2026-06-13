from database import SessionLocal
from models.models import House, PointsConfig, Admin, SchoolClass
from models.models import get_grade_group
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def init_db():
    db = SessionLocal()
    try:
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
                password_hash=hash_password("admin123"),
                role="super_admin"
            )
            db.add(admin)
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

    finally:
        db.close()
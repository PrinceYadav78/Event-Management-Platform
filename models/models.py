from sqlalchemy import Column, String, Integer, Boolean, Date, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

GRADE_GROUPS = {
    "Primary": ["I", "II", "III", "IV"],
    "Middle": ["V", "VI", "VII", "VIII"],
    "Senior": ["IX", "X", "XI", "XII"]
}

def get_grade_group(class_name: str) -> str:
    if not class_name:
        return "Primary"
    
    # Extract just the grade part (before the section letter)
    # e.g. "IX A" -> "IX", "XII B" -> "XII", "I A" -> "I"
    parts = class_name.strip().split()
    if not parts:
        return "Primary"
    
    grade = parts[0].upper().strip()
    
    # Check longest matches first to avoid "I" matching "IX" or "II" matching "XII"
    # Order matters — check XII before XI before X, IX before I, etc.
    senior_grades = ["XII", "XI", "IX", "X"]
    middle_grades = ["VIII", "VII", "VI", "V"]
    primary_grades = ["IV", "III", "II", "I"]
    
    if grade in senior_grades:
        return "Senior"
    elif grade in middle_grades:
        return "Middle"
    elif grade in primary_grades:
        return "Primary"
    else:
        return "Primary"

class House(Base):
    __tablename__ = "houses"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(50), nullable=False)
    color = Column(String(20), nullable=False)
    total_points = Column(Integer, default=0)
    primary_points = Column(Integer, default=0)
    middle_points = Column(Integer, default=0)
    senior_points = Column(Integer, default=0)

    students = relationship("Student", back_populates="house")

class Student(Base):
    __tablename__ = "students"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    roll_number = Column(String(20), unique=True, nullable=False)
    class_name = Column(String(10), nullable=False)
    grade_group = Column(String(20), nullable=False)
    house_id = Column(String, ForeignKey("houses.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    house = relationship("House", back_populates="students")
    participations = relationship("EventParticipant", back_populates="student", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)
    event_date = Column(Date, nullable=False)
    event_type = Column(String(20), default="individual")
    grade_group = Column(String(20), nullable=False)
    is_completed = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    participants = relationship("EventParticipant", back_populates="event", cascade="all, delete-orphan")

class EventParticipant(Base):
    __tablename__ = "event_participants"

    id = Column(String, primary_key=True, default=generate_uuid)
    event_id = Column(String, ForeignKey("events.id"), nullable=False)
    student_id = Column(String, ForeignKey("students.id"), nullable=False)
    position = Column(Integer, nullable=True)
    points_awarded = Column(Integer, default=0)

    event = relationship("Event", back_populates="participants")
    student = relationship("Student", back_populates="participations")

class PointsConfig(Base):
    __tablename__ = "points_config"

    id = Column(String, primary_key=True, default=generate_uuid)
    position = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False)
    is_default = Column(Boolean, default=False)
    label = Column(String(50), nullable=True)

class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False)
    title_text = Column(String(200), default="Certificate of Achievement")
    body_text = Column(Text, default="This is to certify that {name} has won {position} place in {event}")
    font_family = Column(String(50), default="Helvetica")
    updated_at = Column(DateTime, server_default=func.now())

class Admin(Base):
    __tablename__ = "admins"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), default="admin")
    created_at = Column(DateTime, server_default=func.now())
class SchoolClass(Base):
    __tablename__ = "school_classes"

    id = Column(String, primary_key=True, default=generate_uuid)
    class_name = Column(String(20), unique=True, nullable=False)
    grade_group = Column(String(20), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class TermSettings(Base):
    __tablename__ = "term_settings"

    id = Column(String, primary_key=True, default=generate_uuid)
    term_name = Column(String(100), nullable=False, default="Term 1")
    is_locked = Column(Boolean, default=False)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
class CustomTemplate(Base):
    __tablename__ = "custom_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    filename = Column(String(200), nullable=False)
    file_type = Column(String(10), nullable=False, default="image")
    is_default = Column(Boolean, default=False)

    # Text overlay settings (for image templates)
    name_x = Column(Integer, default=50)
    name_y = Column(Integer, default=45)
    name_font_size = Column(Integer, default=36)
    name_color = Column(String(20), default="#1a2535")

    event_x = Column(Integer, default=50)
    event_y = Column(Integer, default=58)
    event_font_size = Column(Integer, default=20)
    event_color = Column(String(20), default="#374151")

    position_x = Column(Integer, default=50)
    position_y = Column(Integer, default=65)
    position_font_size = Column(Integer, default=24)
    position_color = Column(String(20), default="#b45309")

    house_x = Column(Integer, default=50)
    house_y = Column(Integer, default=72)
    house_font_size = Column(Integer, default=16)
    house_color = Column(String(20), default="#374151")

    date_x = Column(Integer, default=50)
    date_y = Column(Integer, default=78)
    date_font_size = Column(Integer, default=14)
    date_color = Column(String(20), default="#6b7280")

    created_at = Column(DateTime, server_default=func.now())
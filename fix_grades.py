from app.database import SessionLocal
from app.models.models import Student, get_grade_group

db = SessionLocal()
students = db.query(Student).all()
fixed = 0
for student in students:
    correct_group = get_grade_group(student.class_name)
    if student.grade_group != correct_group:
        print(f"Fixing {student.name} ({student.class_name}): {student.grade_group} → {correct_group}")
        student.grade_group = correct_group
        fixed += 1
db.commit()
print(f"Fixed {fixed} students!")
db.close()
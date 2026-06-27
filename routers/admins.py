"""Super-admin only: bulk-generate teacher admin logins from a CSV of names.

Upload a CSV whose first column is headed `name` (teacher names below it).
On upload, every existing non-super-admin account is wiped and a fresh login +
random password is generated for each name. Passwords avoid ambiguous
characters (I, l, o, 0, plus O and 1) so they're easy to read/type. The plain
passwords are shown once on screen (and downloadable) — they're stored hashed
and cannot be recovered afterwards.
"""
import csv
import io
import re
import secrets

import bcrypt
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models.models import Admin
from routers.auth import verify_token
from templating import templates
from audit import log_action

router = APIRouter()

# Unambiguous alphabet: excludes I, l, o, 0 (requested) plus their look-alikes O and 1.
SAFE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def generate_password(length: int = 10) -> str:
    """Random password from the unambiguous alphabet, guaranteed to mix letters + digits."""
    while True:
        pw = "".join(secrets.choice(SAFE_CHARS) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def make_email(name: str, used: set) -> str:
    """Derive a unique login email like 'anita.verma@nps.com' from a teacher's name."""
    slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
    if not slug:
        slug = "teacher"
    email = f"{slug}@nps.com"
    n = 1
    while email in used:
        n += 1
        email = f"{slug}{n}@nps.com"
    used.add(email)
    return email


def require_super_admin(request: Request, db: Session):
    """Return the Admin row if the caller is a logged-in super_admin, else None."""
    email = verify_token(request)
    if not email:
        return None
    admin = db.query(Admin).filter(Admin.email == email).first()
    if admin and admin.role == "super_admin":
        return admin
    return None


def _existing_admins(db: Session):
    return db.query(Admin).filter(Admin.role == "admin").order_by(Admin.email).all()


@router.get("/admins", response_class=HTMLResponse)
async def admins_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "admin/admins.html", {
        "active": "admins",
        "admins": _existing_admins(db),
        "generated": None,
    })


@router.get("/admins/template")
async def admins_template(request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name"])
    writer.writerow(["Anita Verma"])
    writer.writerow(["Rohan Gupta"])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=teachers_template.csv"},
    )


@router.post("/admins/generate", response_class=HTMLResponse)
async def admins_generate(request: Request, db: Session = Depends(get_db)):
    if not require_super_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)

    form = await request.form()
    file = form.get("csv_file")
    if not file:
        return templates.TemplateResponse(request, "admin/admins.html", {
            "active": "admins", "admins": _existing_admins(db), "generated": None,
            "error": "Please choose a CSV file first.",
        })

    contents = await file.read()
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = contents.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))

    # Pull the 'name' column case-insensitively; fall back to the first column.
    names = []
    for row in reader:
        value = None
        for key, val in row.items():
            if key and key.strip().lower() == "name":
                value = val
                break
        if value is None and row:
            value = next(iter(row.values()), None)
        if value and value.strip():
            names.append(value.strip())

    # De-duplicate names (case-insensitive), preserving order.
    seen, unique_names = set(), []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique_names.append(name)

    if not unique_names:
        return templates.TemplateResponse(request, "admin/admins.html", {
            "active": "admins", "admins": _existing_admins(db), "generated": None,
            "error": "No names found. Make sure column A has a 'name' header with teacher names below it.",
        })

    # Wipe all non-super-admin accounts, then generate fresh logins.
    # Use ORM deletes (not a bulk delete) so each removal also syncs to Firestore.
    for old_admin in db.query(Admin).filter(Admin.role != "super_admin").all():
        db.delete(old_admin)
    db.commit()

    used_emails = {a.email for a in db.query(Admin).all()}
    generated = []
    for name in unique_names:
        email = make_email(name, used_emails)
        password = generate_password()
        db.add(Admin(email=email, name=name, password_hash=hash_password(password), role="admin"))
        generated.append({"name": name, "email": email, "password": password})
    db.commit()
    log_action(db, request, "Generated teacher logins", f"{len(generated)} account(s) created")

    return templates.TemplateResponse(request, "admin/admins.html", {
        "active": "admins",
        "admins": _existing_admins(db),
        "generated": generated,
    })

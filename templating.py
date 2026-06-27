"""Shared Jinja2 templates instance.

Centralising the templates object lets us register template globals (like
`current_role`) once and have them available on every rendered page — e.g. so
the sidebar can show the super-admin-only "Admins" link.
"""
import os
from fastapi.templating import Jinja2Templates
from jose import jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key-do-not-use-in-prod")
ALGORITHM = "HS256"

templates = Jinja2Templates(directory="templates")


def _payload(request):
    token = request.cookies.get("access_token")
    if not token:
        return {}
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return {}


def current_role(request):
    """Return the role ('super_admin' / 'admin') from the request's JWT cookie."""
    return _payload(request).get("role")


def current_user(request):
    """Return {name, email, role} for the logged-in admin, for the sidebar."""
    p = _payload(request)
    email = p.get("sub")
    role = p.get("role")
    name = p.get("name")
    # Friendly fallbacks so the sidebar never shows a blank.
    if not name:
        name = "Super Admin" if role == "super_admin" else (email.split("@")[0].replace(".", " ").title() if email else "Admin")
    return {"name": name, "email": email, "role": role}


def current_term():
    """Active term info for the sidebar / banner: {state, name, year}."""
    from database import SessionLocal
    from terms import term_state
    db = SessionLocal()
    try:
        state, t = term_state(db)
        return {"state": state, "name": (t.term_name if t else None), "year": (t.academic_year if t else None)}
    except Exception:
        return {"state": "none", "name": None, "year": None}
    finally:
        db.close()


# Make these callable from any template.
templates.env.globals["current_role"] = current_role
templates.env.globals["current_user"] = current_user
templates.env.globals["current_term"] = current_term

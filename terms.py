"""Helpers for terms — supports multiple terms with one active term.

The "active" term is the one currently in effect; its lock state controls
whether admins can edit students/events/results.
"""
import datetime

from models.models import TermSettings


def get_active_term(db):
    """The active term, or None if there isn't one."""
    return db.query(TermSettings).filter(TermSettings.is_active == True).first()  # noqa: E712


def term_state(db):
    """Return ('active'|'locked'|'none', term_or_None)."""
    term = get_active_term(db)
    if not term:
        return ("none", None)
    if term.is_locked:
        return ("locked", term)
    return ("active", term)


def is_term_locked(db) -> bool:
    """Edits are blocked when there is no active term OR the active term is locked."""
    state, _ = term_state(db)
    return state != "active"


def default_academic_year() -> str:
    """e.g. '2026-27' — academic year starting in the April–March cycle."""
    today = datetime.date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str((start + 1) % 100).zfill(2)}"

"""Tiny accessor for the single-row app config."""
from models.models import AppConfig


def get_config(db):
    return db.query(AppConfig).first()


def teachers_can_delete(db) -> bool:
    cfg = db.query(AppConfig).first()
    return bool(cfg.teachers_can_delete) if cfg else False

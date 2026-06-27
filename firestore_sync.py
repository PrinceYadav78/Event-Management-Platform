"""Keeps the local SQLite mirror and Firestore in sync — SYNCHRONOUSLY.

Firestore is the source of truth. On startup the app PULLS from Firestore into
the local SQLite mirror (`hydrate_from_firestore`). When an admin makes a change,
the affected records are written to Firestore *inside the same request* (during
commit), so a change is durable in Firestore before the response returns.

This makes the app safe on ephemeral / scale-to-zero hosting (e.g. Cloud Run,
min-instances=0): if the instance is killed or restarts, nothing is lost — it
re-hydrates from Firestore on the next start. Run it as a SINGLE instance
(max-instances=1) so there is only ever one mirror.
"""
import datetime
import threading

from sqlalchemy import Date, DateTime, event
from sqlalchemy.orm import Session

from database import SessionLocal
from firestore_db import get_client
from models.models import (
    House, Student, Event, EventParticipant, PointsConfig,
    CertificateTemplate, Admin, SchoolClass, TermSettings, CustomTemplate, AuditLog,
)

MODELS = [
    House, Student, Event, EventParticipant, PointsConfig,
    CertificateTemplate, Admin, SchoolClass, TermSettings, CustomTemplate, AuditLog,
]
_MODEL_SET = set(MODELS)
_BATCH_LIMIT = 400  # Firestore allows up to 500 writes per batch


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def _serialize(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def row_to_dict(row):
    return {c.name: _serialize(getattr(row, c.name)) for c in row.__table__.columns}


def _deserialize_row(Model, data):
    cols = {c.name: c for c in Model.__table__.columns}
    out = {}
    for key, val in data.items():
        col = cols.get(key)
        if col is None:
            continue
        if isinstance(val, str) and isinstance(col.type, DateTime):
            try:
                val = datetime.datetime.fromisoformat(val)
            except ValueError:
                pass
        elif isinstance(val, str) and isinstance(col.type, Date):
            try:
                val = datetime.date.fromisoformat(val)
            except ValueError:
                pass
        out[key] = val
    return out


# --------------------------------------------------------------------------- #
# Suppression — so the startup hydrate (which writes to SQLite) is not echoed
# back up to Firestore.
# --------------------------------------------------------------------------- #
_local = threading.local()


def _suppressed():
    return getattr(_local, "suppress", False)


class suppress_sync:
    def __enter__(self):
        _local.suppress = True

    def __exit__(self, *exc):
        _local.suppress = False


# --------------------------------------------------------------------------- #
# Capture changed rows during flush, push them to Firestore on commit.
# --------------------------------------------------------------------------- #
@event.listens_for(Session, "after_flush")
def _capture(session, flush_context):
    if _suppressed():
        return
    pend = session.info.setdefault("_fs", {"upsert": [], "delete": []})
    for obj in session.new:
        if type(obj) in _MODEL_SET and getattr(obj, "id", None) is not None:
            pend["upsert"].append((type(obj), str(obj.id)))
    for obj in session.dirty:
        if (type(obj) in _MODEL_SET and getattr(obj, "id", None) is not None
                and session.is_modified(obj, include_collections=False)):
            pend["upsert"].append((type(obj), str(obj.id)))
    for obj in session.deleted:
        if type(obj) in _MODEL_SET and getattr(obj, "id", None) is not None:
            pend["delete"].append((type(obj).__tablename__, str(obj.id)))


@event.listens_for(Session, "after_commit")
def _push_to_firestore(session):
    """Write just-committed changes to Firestore SYNCHRONOUSLY (durable on commit)."""
    pend = session.info.pop("_fs", None)
    if not pend or _suppressed():
        return
    try:
        fs = get_client()
        batch = fs.batch()
        n = 0
        seen = set()
        db2 = SessionLocal()
        try:
            for Model, doc_id in pend["upsert"]:
                key = (Model.__tablename__, doc_id)
                if key in seen:
                    continue
                seen.add(key)
                row = db2.query(Model).filter(Model.id == doc_id).first()
                if row is None:
                    continue
                batch.set(fs.collection(Model.__tablename__).document(doc_id), row_to_dict(row))
                n += 1
                if n >= _BATCH_LIMIT:
                    batch.commit(); batch = fs.batch(); n = 0
            for table, doc_id in pend["delete"]:
                batch.delete(fs.collection(table).document(doc_id))
                n += 1
                if n >= _BATCH_LIMIT:
                    batch.commit(); batch = fs.batch(); n = 0
        finally:
            db2.close()
        if n:
            batch.commit()
    except Exception as e:
        print("[firestore] write failed (change kept locally, retry on next edit):", e)


@event.listens_for(Session, "after_rollback")
def _discard(session):
    session.info.pop("_fs", None)


# --------------------------------------------------------------------------- #
# Startup hydrate (Firestore -> local mirror). Never writes to Firestore.
# --------------------------------------------------------------------------- #
def hydrate_from_firestore():
    """Rebuild the local SQLite mirror from Firestore. Firestore is left untouched."""
    fs = get_client()
    db = SessionLocal()
    loaded = 0
    try:
        with suppress_sync():
            for Model in MODELS:
                db.query(Model).delete()
            db.commit()
            for Model in MODELS:
                for doc in fs.collection(Model.__tablename__).stream():
                    db.add(Model(**_deserialize_row(Model, doc.to_dict())))
                    loaded += 1
            db.commit()
        return loaded
    finally:
        db.close()


def full_sync_to_firestore():
    """Manual one-shot: push the entire local state to Firestore (not used at runtime)."""
    fs = get_client()
    db = SessionLocal()
    try:
        for Model in MODELS:
            coll = Model.__tablename__
            local_ids = set()
            batch = fs.batch(); pending = 0
            for row in db.query(Model).all():
                data = row_to_dict(row); doc_id = str(data.get("id"))
                local_ids.add(doc_id)
                batch.set(fs.collection(coll).document(doc_id), data); pending += 1
                if pending >= _BATCH_LIMIT:
                    batch.commit(); batch = fs.batch(); pending = 0
            if pending:
                batch.commit()
            remote_ids = [d.id for d in fs.collection(coll).stream()]
            dbatch = fs.batch(); pending = 0
            for doc_id in [i for i in remote_ids if i not in local_ids]:
                dbatch.delete(fs.collection(coll).document(doc_id)); pending += 1
                if pending >= _BATCH_LIMIT:
                    dbatch.commit(); dbatch = fs.batch(); pending = 0
            if pending:
                dbatch.commit()
    finally:
        db.close()

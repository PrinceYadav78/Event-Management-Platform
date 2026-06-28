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
import time

from sqlalchemy import Date, DateTime, event
from sqlalchemy.orm import Session

import live
from database import SessionLocal
from firestore_db import get_client
from models.models import (
    House, Student, Event, EventParticipant, PointsConfig,
    CertificateTemplate, Admin, SchoolClass, TermSettings, CustomTemplate, AuditLog, AppConfig,
)

MODELS = [
    House, Student, Event, EventParticipant, PointsConfig,
    CertificateTemplate, Admin, SchoolClass, TermSettings, CustomTemplate, AuditLog, AppConfig,
]
_MODEL_SET = set(MODELS)
_BATCH_LIMIT = 400  # Firestore allows up to 500 writes per batch

# Logical uniqueness used to DEDUPE on hydrate, so a duplicate in Firestore can
# never abort the whole load. (table -> (key columns, optional "keep-best" sorter)).
# Without a sorter we keep the OLDEST row (by created_at) — that's the genuine one;
# any newer copies are re-seed pollution. Houses have no created_at, so we keep the
# row with the most points; terms prefer the active one.
_DEDUPE = {
    "houses":         (["name"],                        lambda d: (d.get("total_points") or 0)),
    "students":       (["roll_number"],                 None),
    "admins":         (["email"],                       None),
    "school_classes": (["class_name"],                  None),
    "points_config":  (["position"],                    None),
    "term_settings":  (["term_name", "academic_year"],  lambda d: 1 if d.get("is_active") else 0),
    "app_config":     ([],                              None),  # singleton
}


def _dedupe_docs(table, docs):
    spec = _DEDUPE.get(table)
    if spec is None:
        return docs  # events, participants, templates, audit logs — no logical dupes
    keys, prefer = spec
    if prefer is not None:
        docs = sorted(docs, key=prefer, reverse=True)        # best (e.g. most points) kept
    else:
        docs = sorted(docs, key=lambda d: (d.get("created_at") or "0"))  # oldest kept
    seen, out = set(), []
    for d in docs:
        k = tuple(d.get(c) for c in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


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


# Set when a push fails — the next successful commit reconciles the whole state.
_unsynced = False


def _commit_with_retry(batch, attempts=3):
    last = None
    for i in range(attempts):
        try:
            batch.commit()
            return
        except Exception as e:
            last = e
            time.sleep(0.4 * (i + 1))
    raise last


@event.listens_for(Session, "after_commit")
def _push_to_firestore(session):
    """Write just-committed changes to Firestore SYNCHRONOUSLY, with retry + reconcile."""
    global _unsynced
    pend = session.info.pop("_fs", None)
    if _suppressed() or (not pend and not _unsynced):
        return
    try:
        # If an earlier push failed, re-push the entire local state to catch up.
        if _unsynced:
            full_sync_to_firestore()
            _unsynced = False
        if pend:
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
                        _commit_with_retry(batch); batch = fs.batch(); n = 0
                for table, doc_id in pend["delete"]:
                    batch.delete(fs.collection(table).document(doc_id))
                    n += 1
                    if n >= _BATCH_LIMIT:
                        _commit_with_retry(batch); batch = fs.batch(); n = 0
            finally:
                db2.close()
            if n:
                _commit_with_retry(batch)
    except Exception as e:
        _unsynced = True  # reconcile on the next change
        print("[firestore] write failed (kept locally, will reconcile on next change):", e)
    # Notify connected browsers (SSE) that data changed — even if the Firestore
    # push failed, the change IS in the shared local mirror.
    live.bump()


@event.listens_for(Session, "after_rollback")
def _discard(session):
    session.info.pop("_fs", None)


# --------------------------------------------------------------------------- #
# Startup hydrate (Firestore -> local mirror). Never writes to Firestore.
# --------------------------------------------------------------------------- #
def hydrate_from_firestore():
    """Rebuild the local SQLite mirror from Firestore. Firestore is left untouched.

    Hardened against duplicate data:
      * Each collection is DE-DUPED before insert, so a duplicate (e.g. two rows
        with the same admin email) can never raise a UNIQUE error mid-load.
      * Clear + insert happen in ONE transaction, so if anything still fails the
        whole thing rolls back and the mirror keeps its previous data — it is
        never left empty (an empty mirror used to make init_db re-seed and push
        fresh duplicates back to Firestore, compounding the problem on every restart).
    """
    fs = get_client()
    db = SessionLocal()
    loaded = 0
    try:
        with suppress_sync():
            # Read + dedupe everything from Firestore first.
            staged = []
            for Model in MODELS:
                docs = [d.to_dict() for d in fs.collection(Model.__tablename__).stream()]
                staged.append((Model, _dedupe_docs(Model.__tablename__, docs)))
            # Single transaction: clear then insert; commit once.
            for Model in MODELS:
                db.query(Model).delete()
            for Model, docs in staged:
                for data in docs:
                    db.add(Model(**_deserialize_row(Model, data)))
                    loaded += 1
            db.commit()
        return loaded
    except Exception:
        db.rollback()
        raise
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

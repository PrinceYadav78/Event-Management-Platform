"""Real-time Firestore -> local mirror sync via on_snapshot listeners.

Lets edits made OUTSIDE this process (the Firebase console, or another instance)
flow into the running app within ~a second. Each collection gets a listener; when
Firestore reports a change we apply it to the SQLite mirror (suppressed, so it is
not echoed back up) and bump the live version so connected browsers refresh.

NOTE: listeners are long-lived background gRPC streams — they only work while the
instance is awake, so this needs an always-on instance (not scale-to-zero).
"""
from google.cloud.firestore_v1.watch import ChangeType

import live
from database import SessionLocal
from firestore_db import get_client
from firestore_sync import MODELS, _deserialize_row, suppress_sync

_watches = []
_initialized = set()  # tables whose initial full snapshot we've already skipped


def start_listeners():
    """Attach an on_snapshot listener to every collection. Safe to call once."""
    if _watches:
        return
    fs = get_client()
    for Model in MODELS:
        _watches.append(fs.collection(Model.__tablename__).on_snapshot(_make_cb(Model)))
    print(f"[realtime] attached {len(_watches)} Firestore listener(s)")


def stop_listeners():
    for w in _watches:
        try:
            w.unsubscribe()
        except Exception:
            pass
    _watches.clear()
    _initialized.clear()


def _make_cb(Model):
    table = Model.__tablename__

    def cb(col_snapshot, changes, read_time):
        # The first callback is the initial full snapshot — the startup hydrate
        # already loaded that, so skip it (avoids a redundant rewrite + version bump).
        if table not in _initialized:
            _initialized.add(table)
            return
        try:
            _apply_changes(Model, changes)
        except Exception as e:
            print(f"[realtime] {table} listener error:", e)

    return cb


def _apply_changes(Model, changes):
    db = SessionLocal()
    changed = False
    try:
        with suppress_sync():  # don't echo these writes back to Firestore
            for ch in changes:
                doc_id = ch.document.id
                if ch.type == ChangeType.REMOVED:
                    row = db.query(Model).filter(Model.id == doc_id).first()
                    if row is not None:
                        db.delete(row)
                        changed = True
                else:  # ADDED or MODIFIED -> upsert by id
                    data = _deserialize_row(Model, ch.document.to_dict() or {})
                    row = db.query(Model).filter(Model.id == doc_id).first()
                    if row is None:
                        db.add(Model(**data))
                    else:
                        for k, v in data.items():
                            if k != "id":
                                setattr(row, k, v)
                    changed = True
            if changed:
                db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    if changed:
        live.bump()

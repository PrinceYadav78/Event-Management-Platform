"""Tiny in-memory 'something changed' counter for real-time updates.

Bumped whenever the data changes — by an admin's commit (firestore_sync) or by a
Firestore listener seeing an external/console edit (realtime). Browsers hold an
SSE connection (see main.py /realtime/stream) that watches this counter and
refreshes the page when it moves. No app imports here, so nothing can import-cycle.
"""
import threading

_version = 0
_lock = threading.Lock()


def bump():
    global _version
    with _lock:
        _version += 1


def get_version() -> int:
    with _lock:
        return _version

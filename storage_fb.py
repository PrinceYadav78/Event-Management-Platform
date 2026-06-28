"""Firebase Cloud Storage helper — durable storage for uploaded files
(certificate templates), so they survive restarts and have no size cap.

Uses the same service-account credentials as Firestore.
"""
import os

from google.cloud import storage

from firestore_db import _load_service_account_info

BUCKET_NAME = os.getenv("FIREBASE_STORAGE_BUCKET", "key-period-473405-g2.firebasestorage.app")

_bucket = None


def get_bucket():
    global _bucket
    if _bucket is None:
        from google.oauth2 import service_account
        info = _load_service_account_info()
        creds = service_account.Credentials.from_service_account_info(info)
        client = storage.Client(project=info["project_id"], credentials=creds)
        _bucket = client.bucket(BUCKET_NAME)
    return _bucket


def upload_bytes(path: str, data: bytes, content_type: str = None) -> str:
    blob = get_bucket().blob(path)
    blob.upload_from_string(data, content_type=content_type)
    return path


def download_bytes(path: str) -> bytes:
    return get_bucket().blob(path).download_as_bytes()


def delete_blob(path: str):
    try:
        get_bucket().blob(path).delete()
    except Exception:
        pass

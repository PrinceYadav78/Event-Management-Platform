"""Firestore connection for the named database.

Authenticates with the Firebase service-account key and targets the specific
named Firestore database (NOT the project's default database). All app data
lives in this one database.
"""
import json
import os

from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

# Path to the service-account key (gitignored). Override via env if you rename it.
KEY_PATH = os.getenv(
    "FIREBASE_KEY",
    "key-period-473405-g2-firebase-adminsdk-fbsvc-2d943f120e.json",
)

# The specific named database the data must go to.
DATABASE_ID = os.getenv(
    "FIRESTORE_DATABASE",
    "ai-studio-5c89681c-cdd0-4be4-8754-2183d8282c52",
)

_client = None


def get_client() -> firestore.Client:
    """Return a cached Firestore client bound to the named database."""
    global _client
    if _client is None:
        with open(KEY_PATH, encoding="utf-8") as f:
            project_id = json.load(f)["project_id"]
        creds = service_account.Credentials.from_service_account_file(KEY_PATH)
        _client = firestore.Client(
            project=project_id,
            credentials=creds,
            database=DATABASE_ID,
        )
    return _client

"""Local SQLite mirror of the Firestore database.

Firestore is the source of truth (see firestore_sync.py): this SQLite file is
rebuilt from Firestore on startup and every change is written back to Firestore.
It is kept purely so the app's existing relational queries (joins, house-point
aggregation, cascade deletes) keep working unchanged.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Local mirror file. Override with MIRROR_DATABASE_URL if you want it elsewhere.
MIRROR_DATABASE_URL = os.getenv("MIRROR_DATABASE_URL", "sqlite:///./school_events.db")

engine = create_engine(
    MIRROR_DATABASE_URL,
    # timeout lets concurrent writers (e.g. the real-time listener thread) wait
    # on the lock instead of erroring with "database is locked".
    connect_args={"check_same_thread": False, "timeout": 20} if MIRROR_DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

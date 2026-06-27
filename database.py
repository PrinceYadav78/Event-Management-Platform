import os
import time
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./school_events.db")

# How many times to retry a failed connection, and how long to wait between tries.
# This makes the app resilient to transient DNS / network hiccups when reaching the
# cloud (Neon) database, or to the database briefly waking from auto-suspend.
DB_CONNECT_RETRIES = 4
DB_CONNECT_RETRY_DELAY = 1.5  # seconds


def _connect_with_retry(connect_fn):
    """Open a DBAPI connection, retrying on transient errors (e.g. DNS failures)."""
    last_exc = None
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            return connect_fn()
        except Exception as exc:  # psycopg2.OperationalError, socket errors, etc.
            last_exc = exc
            if attempt == DB_CONNECT_RETRIES:
                break
            print(
                f"[database] connection attempt {attempt}/{DB_CONNECT_RETRIES} failed: "
                f"{exc!s} -- retrying in {DB_CONNECT_RETRY_DELAY}s"
            )
            time.sleep(DB_CONNECT_RETRY_DELAY)
    # All attempts exhausted; re-raise the last error so the request still 500s cleanly.
    raise last_exc


if SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
    import psycopg2

    # A valid SQLAlchemy postgres URL is also a valid libpq connection URI,
    # so we can hand it straight to psycopg2.connect inside the retry wrapper.
    def _pg_creator():
        return _connect_with_retry(lambda: psycopg2.connect(SQLALCHEMY_DATABASE_URL))

    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        creator=_pg_creator,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""One-time data migration: copy every table from the old Neon Postgres database
into the named Firestore database.

Reads Neon DIRECTLY using DATABASE_URL from .env (independent of the app's
database.py, which now points at the local SQLite mirror). Non-destructive — it
only READS from Neon and writes copies to Firestore. Idempotent (same row id ->
same doc id), so it's safe to re-run.

    python migrate_to_firestore.py
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from firestore_db import get_client
from firestore_sync import MODELS, row_to_dict

load_dotenv()

NEON_URL = os.getenv("DATABASE_URL")


def main():
    if not NEON_URL or not NEON_URL.startswith("postgres"):
        raise SystemExit(
            "DATABASE_URL (Neon Postgres) not found in .env — nothing to migrate from."
        )

    neon_engine = create_engine(NEON_URL, pool_pre_ping=True)
    NeonSession = sessionmaker(bind=neon_engine)
    db = NeonSession()
    fs = get_client()

    summary = {}
    try:
        for Model in MODELS:
            coll = Model.__tablename__
            rows = db.query(Model).all()
            batch = fs.batch()
            pending = 0
            for row in rows:
                data = row_to_dict(row)
                batch.set(fs.collection(coll).document(str(data.get("id"))), data)
                pending += 1
                if pending >= 400:
                    batch.commit(); batch = fs.batch(); pending = 0
            if pending:
                batch.commit()
            summary[coll] = len(rows)
            print(f"  {coll:<22} migrated {len(rows)} row(s)")
    finally:
        db.close()

    print("\nVerifying Firestore document counts:")
    all_ok = True
    for coll, src in summary.items():
        got = sum(1 for _ in fs.collection(coll).stream())
        if got != src:
            all_ok = False
        print(f"  {coll:<22} source={src:<5} firestore={got:<5} [{'OK' if got == src else 'MISMATCH'}]")

    print("\nMIGRATION COMPLETE." if all_ok else "\nMIGRATION FINISHED WITH MISMATCHES.")


if __name__ == "__main__":
    main()

"""Load patients and their documents into the portal, and create team logins.

    python -m scripts.seed                      # loads sample_data/
    python -m scripts.seed --data /path/to/real_profiles
    python -m scripts.seed --reset              # wipe the database and files first

Folder layout expected:
    <data>/profiles.json                 list of patient profiles (fields as in the Patient model)
    <data>/patients/<PATIENT_ID>/*       that patient's documents (pdf, jpg, png, docx, txt)

Logins created (change the passwords from the Account page, or set SEED_* env vars first):
    admin / SEED_ADMIN_PASSWORD (default admin12345)
    staff / SEED_STAFF_PASSWORD (default staff12345)
    <patient id in lower case> / SEED_PATIENT_PASSWORD (default patient12345), e.g. pt-0001
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import pipeline, storage  # noqa: E402
from app.config import BASE_DIR, settings  # noqa: E402
from app.db import Base, engine, init_db, session_scope  # noqa: E402
from app.models import Document, Patient, User  # noqa: E402
from app.security import hash_password  # noqa: E402

FIELDS = {c.name for c in Patient.__table__.columns} - {"id", "created_at"}


def ensure_user(db, username, password, role, full_name="", patient_id=None):
    u = db.scalar(select(User).where(User.username == username))
    if u:
        return u
    u = User(username=username, password_hash=hash_password(password), role=role, full_name=full_name,
             patient_id=patient_id)
    db.add(u)
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(BASE_DIR / "sample_data"))
    ap.add_argument("--reset", action="store_true", help="delete all existing data first")
    ap.add_argument("--no-classify", action="store_true", help="skip reading/classifying documents now")
    args = ap.parse_args()
    data = Path(args.data)

    if args.reset:
        Base.metadata.drop_all(engine)
        shutil.rmtree(settings.files_dir, ignore_errors=True)
    init_db()

    profiles = json.loads((data / "profiles.json").read_text(encoding="utf-8"))
    new_docs = []
    with session_scope() as db:
        ensure_user(db, "admin", os.getenv("SEED_ADMIN_PASSWORD", "admin12345"), "admin", "Administrator")
        ensure_user(db, "staff", os.getenv("SEED_STAFF_PASSWORD", "staff12345"), "staff", "Claims Agent")
        for prof in profiles:
            code = prof["patient_code"]
            p = db.scalar(select(Patient).where(Patient.patient_code == code))
            if not p:
                p = Patient(**{k: v for k, v in prof.items() if k in FIELDS})
                db.add(p)
                db.flush()
                print(f"+ patient {code} {p.full_name}")
            ensure_user(db, code.lower(), os.getenv("SEED_PATIENT_PASSWORD", "patient12345"), "patient",
                        p.full_name, p.id)
            folder = data / "patients" / code
            have = {d.sha256 for d in p.documents}
            for f in sorted(folder.glob("*")) if folder.exists() else []:
                if f.suffix.lower() not in storage.ALLOWED_EXTENSIONS:
                    continue
                info = storage.save_bytes(code, f.name, f.read_bytes())
                if info["sha256"] in have:
                    storage.delete(info["stored_name"])
                    continue
                d = Document(patient_id=p.id, original_name=f.name, uploaded_by="seed", **info)
                db.add(d)
                db.flush()
                new_docs.append(d.id)
                have.add(info["sha256"])
    print(f"Added {len(new_docs)} documents.")
    if not args.no_classify:
        for i, doc_id in enumerate(new_docs, 1):
            pipeline.process_document(doc_id, recheck=False)
            print(f"  read and sorted {i}/{len(new_docs)}", end="\r")
        print()
        with session_scope() as db:
            for d in db.scalars(select(Document).where(Document.id.in_(new_docs))).all():
                print(f"  {d.patient.patient_code}  {d.original_name:<28} -> {d.doc_type}")
    print("Done. Sign in as admin / staff (see README for passwords).")


if __name__ == "__main__":
    main()

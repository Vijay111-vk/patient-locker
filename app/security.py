"""Authentication and authorisation.

Roles:
  admin   - everything, plus users, message templates, audit log
  staff   - all patient lockers, upload documents and query letters, see message history
  patient - only their own locker: profile, documents, what is needed, messages; can upload documents
"""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, User

ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except ValueError:
        return False


# ------------------------------------------------------------- login throttling
_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW = 5, 300


def login_blocked(key: str) -> bool:
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < WINDOW]
    return len(_failures[key]) >= MAX_FAILURES


def record_failure(key: str) -> None:
    _failures[key].append(time.time())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


# ------------------------------------------------------------- session helpers
class NotAuthenticated(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    if not uid:
        raise NotAuthenticated()
    user = db.get(User, uid)
    if not user or not user.is_active or request.session.get("pwv") != user.password_hash[-12:]:
        request.session.clear()
        raise NotAuthenticated()
    return user


def require_staff(user: User = Depends(current_user)) -> User:
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="This page is for the claims team only.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can do this.")
    return user


def can_access_patient(user: User, patient_id: int) -> bool:
    if user.role in ("admin", "staff"):
        return True
    return user.role == "patient" and user.patient_id == patient_id


def ensure_patient_access(user: User, patient_id: int) -> None:
    if not can_access_patient(user, patient_id):
        # 404 rather than 403 so a patient cannot probe which IDs exist
        raise HTTPException(status_code=404, detail="Not found")


# ------------------------------------------------------------- CSRF
def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


def check_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=400, detail="Your session form expired. Go back, refresh the page and try again.")


# ------------------------------------------------------------- audit
def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def audit(db: Session, request: Request | None, user: User | None, action: str,
          patient_id: int | None = None, target: str = "") -> None:
    db.add(AuditLog(username=user.username if user else "anonymous", role=user.role if user else "-",
                    action=action, patient_id=patient_id, target=target[:200],
                    ip=client_ip(request) if request else ""))

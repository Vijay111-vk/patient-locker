import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import llm, messaging, pipeline, storage, taxonomy
from .config import BASE_DIR, settings
from .db import get_db, init_db
from .models import AuditLog, Document, Message, Patient, QueryLetter, User
from .notify import email as email_notify
from .notify import whatsapp as wa_notify
from .privacy import mask_email, mask_phone
from .security import (NotAuthenticated, audit, can_access_patient, check_csrf, clear_failures, csrf_token,
                       current_user, ensure_patient_access, hash_password, login_blocked, record_failure,
                       require_admin, require_staff, verify_password)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    pipeline.resume_pending()
    if settings.SECRET_KEY == "change-me-in-production":
        log.warning("SECRET_KEY is the default value. Set a long random SECRET_KEY before going live.")
    yield


app = FastAPI(title="Patient Locker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, session_cookie="locker_session",
                   max_age=settings.SESSION_HOURS * 3600, same_site="lax", https_only=settings.SECURE_COOKIES)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")

TZ = ZoneInfo(settings.DISPLAY_TZ)
IN_PROGRESS = {"queued", "reading", "analysing", "sending"}
STATUS_TEXT = {
    "queued": "Queued", "reading": "Reading letter", "analysing": "Checking locker", "sending": "Sending",
    "sent": "Patient notified", "no_action": "Nothing needed", "complete": "All received",
    "ready": "Analysed, not sent", "failed": "Needs attention", "failed_send": "Sending failed",
}


def _local(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    if not dt:
        return "—"
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).strftime(fmt)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


templates.env.filters.update(local=_local, size=_size, mask_phone=mask_phone, mask_email=mask_email,
                             doc_label=taxonomy.label)
templates.env.globals.update(STATUS_TEXT=STATUS_TEXT, IN_PROGRESS=IN_PROGRESS, DOC_TYPES=taxonomy.DOC_TYPES)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; script-src 'self'; frame-src 'self'; object-src 'self'")
    if not request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(NotAuthenticated)
async def _not_authed(request: Request, exc: NotAuthenticated):
    if request.url.path.startswith("/api/") or request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html", {"code": exc.status_code, "detail": exc.detail,
                                                              "user": None}, status_code=exc.status_code)


def page(request: Request, name: str, user: User | None, **ctx):
    flashes = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request),
                                                      "flashes": flashes, **ctx})


def flash(request: Request, text: str, kind: str = "ok"):
    request.session.setdefault("flash", []).append({"text": text, "kind": kind})


def back(url: str):
    return RedirectResponse(url, status_code=303)


def _patient_or_404(db: Session, patient_id: int) -> Patient:
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Patient not found")
    return p


# =============================================================== auth

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return page(request, "login.html", None, next=next if next.startswith("/") else "/")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
          csrf_token_: str = Form(..., alias="csrf_token"), db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    key = f"{username.lower()}|{request.client.host if request.client else ''}"
    if login_blocked(key):
        flash(request, "Too many failed attempts. Wait 5 minutes and try again.", "error")
        return back("/login")
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        record_failure(key)
        audit(db, request, None, "login_failed", target=username[:80])
        db.commit()
        flash(request, "Username or password is incorrect.", "error")
        return back(f"/login?next={quote(next)}")
    clear_failures(key)
    request.session.clear()  # prevent session fixation
    request.session.update(uid=user.id, pwv=user.password_hash[-12:], csrf=secrets.token_urlsafe(32))
    audit(db, request, user, "login", patient_id=user.patient_id)
    db.commit()
    return back(next if next.startswith("/") and not next.startswith("//") else "/")


@app.post("/logout")
def logout(request: Request, csrf_token_: str = Form(..., alias="csrf_token")):
    check_csrf(request, csrf_token_)
    request.session.clear()
    return back("/login")


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, user: User = Depends(current_user)):
    return page(request, "account.html", user)


@app.post("/account/password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...),
                    csrf_token_: str = Form(..., alias="csrf_token"), user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    if not verify_password(current, user.password_hash):
        flash(request, "Current password is incorrect.", "error")
        return back("/account")
    if len(new) < 8:
        flash(request, "New password must be at least 8 characters.", "error")
        return back("/account")
    user = db.get(User, user.id)
    user.password_hash = hash_password(new)
    audit(db, request, user, "password_changed", patient_id=user.patient_id)
    db.commit()
    request.session["pwv"] = user.password_hash[-12:]
    flash(request, "Password changed.")
    return back("/account")


# =============================================================== home / dashboard

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: User = Depends(current_user)):
    if user.role == "patient":
        return back(f"/patients/{user.patient_id}")
    return back("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", user: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(Patient).order_by(Patient.full_name)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Patient.full_name.ilike(like), Patient.patient_code.ilike(like),
                              Patient.claim_number.ilike(like), Patient.policy_number.ilike(like)))
    patients = db.scalars(stmt).all()
    rows = []
    for p in patients:
        latest = p.queries[0] if p.queries else None
        open_items = sum(len(x.needed_points) for x in p.queries if x.status in ("sent", "failed_send", "ready"))
        rows.append({"p": p, "docs": len(p.documents), "queries": len(p.queries), "latest": latest,
                     "open_items": open_items})
    recent = db.scalars(select(QueryLetter).order_by(QueryLetter.uploaded_at.desc()).limit(8)).all()
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    stats = {
        "patients": db.scalar(select(func.count(Patient.id))),
        "waiting": db.scalar(select(func.count(QueryLetter.id)).where(QueryLetter.status == "sent")),
        "attention": db.scalar(select(func.count(QueryLetter.id)).where(
            QueryLetter.status.in_(["failed", "failed_send", "ready"]))),
        "sent_24h": db.scalar(select(func.count(Message.id)).where(Message.created_at >= since,
                                                                   Message.status.in_(["sent", "simulated"]))),
        "avg_seconds": db.scalar(select(func.avg(QueryLetter.seconds_to_send)).where(
            QueryLetter.seconds_to_send.is_not(None))),
    }
    return page(request, "dashboard.html", user, rows=rows, recent=recent, stats=stats, q=q,
                any_running=any(r.status in IN_PROGRESS for r in recent))


# =============================================================== patients

PATIENT_FIELDS = ["patient_code", "full_name", "phone", "email", "dob", "gender", "hospital", "insurer",
                  "policy_number", "claim_number", "admission_date", "discharge_date", "diagnosis",
                  "preferred_language"]


def _next_code(db: Session) -> str:
    n = db.scalar(select(func.count(Patient.id))) or 0
    while True:
        n += 1
        code = f"PT-{n:04d}"
        if not db.scalar(select(Patient.id).where(Patient.patient_code == code)):
            return code


@app.get("/patients/new", response_class=HTMLResponse)
def patient_new(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return page(request, "patient_form.html", user, patient=None, suggested_code=_next_code(db))


@app.post("/patients/new")
async def patient_create(request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf_token"))
    data = {f: str(form.get(f, "")).strip() for f in PATIENT_FIELDS}
    data["patient_code"] = data["patient_code"] or _next_code(db)
    if not data["full_name"]:
        flash(request, "Patient name is required.", "error")
        return back("/patients/new")
    if db.scalar(select(Patient.id).where(Patient.patient_code == data["patient_code"])):
        flash(request, f"Patient ID {data['patient_code']} already exists.", "error")
        return back("/patients/new")
    p = Patient(**data)
    db.add(p)
    db.flush()
    if form.get("create_login"):
        temp = secrets.token_urlsafe(9)
        db.add(User(username=p.patient_code.lower(), full_name=p.full_name, role="patient", patient_id=p.id,
                    password_hash=hash_password(temp)))
        flash(request, f"Patient login created. Username: {p.patient_code.lower()}  Temporary password: {temp} "
                       f"(shown once; share it with the patient privately).")
    audit(db, request, user, "patient_created", patient_id=p.id, target=p.patient_code)
    db.commit()
    return back(f"/patients/{p.id}")


@app.get("/patients/{patient_id}/edit", response_class=HTMLResponse)
def patient_edit(request: Request, patient_id: int, user: User = Depends(require_staff),
                 db: Session = Depends(get_db)):
    return page(request, "patient_form.html", user, patient=_patient_or_404(db, patient_id), suggested_code="")


@app.post("/patients/{patient_id}/edit")
async def patient_update(request: Request, patient_id: int, user: User = Depends(require_staff),
                         db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf_token"))
    p = _patient_or_404(db, patient_id)
    for f in PATIENT_FIELDS:
        if f == "patient_code":
            continue
        setattr(p, f, str(form.get(f, getattr(p, f))).strip())
    audit(db, request, user, "patient_updated", patient_id=p.id)
    db.commit()
    flash(request, "Profile saved.")
    return back(f"/patients/{p.id}")


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
def patient_detail(request: Request, patient_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    ensure_patient_access(user, patient_id)
    p = _patient_or_404(db, patient_id)
    audit(db, request, user, "viewed_patient", patient_id=p.id)
    db.commit()
    docs_by_type: dict[str, list] = {}
    for d in p.documents:
        docs_by_type.setdefault(d.doc_type, []).append(d)
    checklist = [(k, taxonomy.label(k), docs_by_type.get(k, [])) for k in
                 ("kyc", "policy_copy", "discharge_summary", "final_bill", "investigation_reports",
                  "consultation_papers", "pharmacy_bills", "cancelled_cheque")]
    open_needs = [(q, pt) for q in p.queries if q.status in ("sent", "failed_send", "ready")
                  for pt in q.points if pt.decision == "needed"]
    running = any(q.status in IN_PROGRESS for q in p.queries) or any(d.status == "processing" for d in p.documents)
    tpl = "patient_self.html" if user.role == "patient" else "patient_detail.html"
    return page(request, tpl, user, p=p, checklist=checklist, open_needs=open_needs, running=running,
                docs_by_id={d.id: d for d in p.documents})


@app.get("/patients/{patient_id}/status")
def patient_status(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_patient_access(user, patient_id)
    p = _patient_or_404(db, patient_id)
    sig = [(q.id, q.status) for q in p.queries] + [(d.id, d.status) for d in p.documents]
    running = any(q.status in IN_PROGRESS for q in p.queries) or any(d.status == "processing" for d in p.documents)
    return {"signature": str(hash(str(sig))), "running": running}


# =============================================================== documents

async def _store_documents(db: Session, p: Patient, files: list[UploadFile], uploader: User) -> tuple[list, list]:
    created, notes = [], []
    existing = {d.sha256 for d in p.documents}
    for f in files:
        if not f or not f.filename:
            continue
        data = await f.read()
        try:
            info = storage.save_bytes(p.patient_code, f.filename, data)
        except storage.UploadError as e:
            notes.append(str(e))
            continue
        if info["sha256"] in existing:
            storage.delete(info["stored_name"])
            notes.append(f"{f.filename} is already in the locker, so it was not added again.")
            continue
        existing.add(info["sha256"])
        d = Document(patient_id=p.id, original_name=f.filename[:255], uploaded_by=uploader.username, **info)
        db.add(d)
        created.append(d)
    db.flush()
    return created, notes


@app.post("/patients/{patient_id}/documents")
async def upload_documents(request: Request, patient_id: int, files: list[UploadFile] = File(...),
                           doc_type: str = Form(""), csrf_token_: str = Form(..., alias="csrf_token"),
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    ensure_patient_access(user, patient_id)
    p = _patient_or_404(db, patient_id)
    created, notes = await _store_documents(db, p, files, user)
    if doc_type and taxonomy.valid_type(doc_type) and user.role != "patient":
        for d in created:
            d.doc_type, d.type_source = doc_type, "manual"
    for d in created:
        audit(db, request, user, "document_uploaded", patient_id=p.id, target=f"document:{d.id}")
    db.commit()
    for d in created:
        pipeline.submit(pipeline.process_document, d.id)
    for n in notes:
        flash(request, n, "error" if "not supported" in n or "larger" in n or "empty" in n else "info")
    if created:
        flash(request, f"{len(created)} document(s) added. They are being read and sorted now.")
    return back(f"/patients/{patient_id}#documents")


@app.get("/documents/{doc_id}/file")
def document_file(request: Request, doc_id: int, download: int = 0, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or not can_access_patient(user, d.patient_id):
        raise HTTPException(404, "Not found")
    audit(db, request, user, "document_opened", patient_id=d.patient_id, target=f"document:{d.id}")
    db.commit()
    return FileResponse(storage.path_for(d.stored_name), media_type=d.mime_type, filename=d.original_name,
                        content_disposition_type="attachment" if download else "inline")


@app.post("/documents/{doc_id}/type")
def document_set_type(request: Request, doc_id: int, doc_type: str = Form(...),
                      csrf_token_: str = Form(..., alias="csrf_token"), user: User = Depends(require_staff),
                      db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    d = db.get(Document, doc_id)
    if not d or not taxonomy.valid_type(doc_type):
        raise HTTPException(404, "Not found")
    d.doc_type, d.type_source = doc_type, "manual"
    audit(db, request, user, "document_type_changed", patient_id=d.patient_id, target=f"document:{d.id}:{doc_type}")
    db.commit()
    pipeline.submit(pipeline.recheck_open_queries, d.patient_id)
    flash(request, f"Marked {d.original_name} as {taxonomy.label(doc_type)}.")
    return back(f"/patients/{d.patient_id}#documents")


@app.post("/documents/{doc_id}/delete")
def document_delete(request: Request, doc_id: int, csrf_token_: str = Form(..., alias="csrf_token"),
                    user: User = Depends(require_staff), db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    pid, name = d.patient_id, d.original_name
    storage.delete(d.stored_name)
    db.delete(d)
    audit(db, request, user, "document_deleted", patient_id=pid, target=name)
    db.commit()
    flash(request, f"Removed {name}.")
    return back(f"/patients/{pid}#documents")


# =============================================================== query letters

@app.post("/patients/{patient_id}/queries")
async def upload_query(request: Request, patient_id: int, file: UploadFile = File(...),
                       csrf_token_: str = Form(..., alias="csrf_token"), user: User = Depends(require_staff),
                       db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    p = _patient_or_404(db, patient_id)
    data = await file.read()
    try:
        info = storage.save_bytes(p.patient_code, file.filename or "query.pdf", data)
    except storage.UploadError as e:
        flash(request, str(e), "error")
        return back(f"/patients/{patient_id}")
    q = QueryLetter(patient_id=p.id, original_name=(file.filename or "query")[:255], uploaded_by=user.username,
                    stored_name=info["stored_name"], mime_type=info["mime_type"], sha256=info["sha256"])
    db.add(q)
    db.flush()
    audit(db, request, user, "query_uploaded", patient_id=p.id, target=f"query:{q.id}")
    db.commit()
    pipeline.submit(pipeline.process_query, q.id)
    return back(f"/queries/{q.id}")


@app.get("/queries/{query_id}", response_class=HTMLResponse)
def query_detail(request: Request, query_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.get(QueryLetter, query_id)
    if not q or not can_access_patient(user, q.patient_id):
        raise HTTPException(404, "Not found")
    if user.role == "patient":
        return back(f"/patients/{q.patient_id}#query-{q.id}")
    return page(request, "query_detail.html", user, q=q, p=q.patient,
                docs_by_id={d.id: d for d in q.patient.documents})


@app.get("/queries/{query_id}/status")
def query_status(query_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.get(QueryLetter, query_id)
    if not q or not can_access_patient(user, q.patient_id):
        raise HTTPException(404, "Not found")
    return {"status": q.status, "label": STATUS_TEXT.get(q.status, q.status), "running": q.status in IN_PROGRESS}


@app.get("/queries/{query_id}/file")
def query_file(request: Request, query_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.get(QueryLetter, query_id)
    if not q or not can_access_patient(user, q.patient_id):
        raise HTTPException(404, "Not found")
    audit(db, request, user, "query_letter_opened", patient_id=q.patient_id, target=f"query:{q.id}")
    db.commit()
    return FileResponse(storage.path_for(q.stored_name), media_type=q.mime_type, filename=q.original_name,
                        content_disposition_type="inline")


@app.post("/queries/{query_id}/reprocess")
def query_reprocess(request: Request, query_id: int, send: str = Form(""),
                    csrf_token_: str = Form(..., alias="csrf_token"), user: User = Depends(require_staff),
                    db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    q = db.get(QueryLetter, query_id)
    if not q:
        raise HTTPException(404, "Not found")
    q.status = "queued"
    q.extracted_text = q.extracted_text if q.extracted_text.strip() else ""
    audit(db, request, user, "query_reprocessed", patient_id=q.patient_id, target=f"query:{q.id}")
    db.commit()
    pipeline.submit(pipeline.process_query, q.id, send=bool(send))
    return back(f"/queries/{q.id}")


@app.post("/queries/{query_id}/send")
def query_send(request: Request, query_id: int, csrf_token_: str = Form(..., alias="csrf_token"),
               user: User = Depends(require_staff), db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    q = db.get(QueryLetter, query_id)
    if not q or not q.points:
        raise HTTPException(404, "Not found")
    q.status = "sending"
    audit(db, request, user, "query_message_resent", patient_id=q.patient_id, target=f"query:{q.id}")
    db.commit()
    pipeline.submit(pipeline.send_messages, q.id)
    flash(request, "Sending the message again on WhatsApp and email.")
    return back(f"/queries/{q.id}")


# =============================================================== admin

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    tpls = {k: messaging.get_template(db, k) for k in messaging.TEMPLATE_FILES}
    integrations = {
        "Reading & matching": ("AI: " + llm.engine_label()) if llm.enabled() else
        "Built-in rules (set LLM_PROVIDER and an API key for better accuracy)",
        "WhatsApp": wa_notify.configured()[1],
        "Email": email_notify.configured()[1],
    }
    overrides = {"WhatsApp test number": settings.TEST_RECIPIENT_PHONE, "Email test address": settings.TEST_RECIPIENT_EMAIL}
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    return page(request, "settings.html", user, tpls=tpls, placeholders=messaging.PLACEHOLDERS,
                integrations=integrations, overrides=overrides, users=users,
                wa_ok=wa_notify.configured()[0], email_ok=email_notify.configured()[0])


@app.post("/settings/templates")
async def settings_templates(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf_token"))
    for key in messaging.TEMPLATE_FILES:
        if key in form:
            messaging.set_template(db, key, str(form[key]).replace("\r\n", "\n"))
    audit(db, request, user, "templates_updated")
    db.commit()
    flash(request, "Message templates saved. New messages will use them.")
    return back("/settings#templates")


@app.post("/settings/users")
def settings_add_user(request: Request, username: str = Form(...), full_name: str = Form(""),
                      role: str = Form(...), password: str = Form(...),
                      csrf_token_: str = Form(..., alias="csrf_token"), user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    if role not in ("admin", "staff"):
        raise HTTPException(400, "Role must be admin or staff")
    if len(password) < 8:
        flash(request, "Password must be at least 8 characters.", "error")
        return back("/settings#users")
    if db.scalar(select(User.id).where(func.lower(User.username) == username.strip().lower())):
        flash(request, "That username is taken.", "error")
        return back("/settings#users")
    db.add(User(username=username.strip(), full_name=full_name.strip(), role=role, password_hash=hash_password(password)))
    audit(db, request, user, "user_created", target=f"{username}:{role}")
    db.commit()
    flash(request, f"Added {username}.")
    return back("/settings#users")


@app.post("/settings/users/{uid}/toggle")
def settings_toggle_user(request: Request, uid: int, csrf_token_: str = Form(..., alias="csrf_token"),
                         user: User = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf_token_)
    u = db.get(User, uid)
    if not u or u.id == user.id:
        raise HTTPException(400, "You cannot change this account here.")
    u.is_active = not u.is_active
    audit(db, request, user, "user_" + ("enabled" if u.is_active else "disabled"), target=u.username)
    db.commit()
    return back("/settings#users")


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, patient_id: int | None = None, user: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(400)
    if patient_id:
        stmt = stmt.where(AuditLog.patient_id == patient_id)
    entries = db.scalars(stmt).all()
    names = {p.id: f"{p.patient_code} {p.full_name}" for p in db.scalars(select(Patient)).all()}
    return page(request, "audit.html", user, entries=entries, names=names, patient_id=patient_id)


# =============================================================== machine API

def _api_auth(request: Request):
    key = request.headers.get("x-api-key", "")
    if not settings.API_KEY or not secrets.compare_digest(key, settings.API_KEY):
        raise HTTPException(401, "Invalid or missing X-API-Key")


def _patient_by_code(db: Session, code: str) -> Patient:
    p = db.scalar(select(Patient).where(Patient.patient_code == code))
    if not p:
        raise HTTPException(404, "Unknown patient ID")
    return p


@app.post("/api/v1/patients/{patient_code}/query-letters", dependencies=[Depends(_api_auth)])
async def api_upload_query(patient_code: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    p = _patient_by_code(db, patient_code)
    data = await file.read()
    try:
        info = storage.save_bytes(p.patient_code, file.filename or "query.pdf", data)
    except storage.UploadError as e:
        raise HTTPException(400, str(e))
    q = QueryLetter(patient_id=p.id, original_name=(file.filename or "query")[:255], uploaded_by="api",
                    stored_name=info["stored_name"], mime_type=info["mime_type"], sha256=info["sha256"])
    db.add(q)
    db.flush()
    db.add(AuditLog(username="api", role="api", action="query_uploaded", patient_id=p.id, target=f"query:{q.id}"))
    db.commit()
    pipeline.submit(pipeline.process_query, q.id)
    return {"query_id": q.id, "status": "queued"}


@app.post("/api/v1/patients/{patient_code}/documents", dependencies=[Depends(_api_auth)])
async def api_upload_documents(patient_code: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    p = _patient_by_code(db, patient_code)
    api_user = User(username="api", role="staff", password_hash="")
    created, notes = await _store_documents(db, p, files, api_user)
    db.commit()
    for d in created:
        pipeline.submit(pipeline.process_document, d.id)
    return {"document_ids": [d.id for d in created], "notes": notes}


@app.get("/api/v1/query-letters/{query_id}", dependencies=[Depends(_api_auth)])
def api_query(query_id: int, db: Session = Depends(get_db)):
    q = db.get(QueryLetter, query_id)
    if not q:
        raise HTTPException(404, "Not found")
    return {"id": q.id, "patient_id": q.patient.patient_code, "status": q.status, "insurer": q.insurer_name,
            "claim_reference": q.claim_reference, "deadline": q.deadline, "seconds_to_send": q.seconds_to_send,
            "points": [{"ref": p.ref, "text": p.insurer_text, "kind": p.kind, "decision": p.decision,
                        "requested_types": p.requested_types, "matched_document_ids": p.matched_document_ids,
                        "reason": p.reason, "patient_request": p.patient_request} for p in q.points],
            "messages": [{"channel": m.channel, "status": m.status, "error": m.error,
                          "at": m.created_at.isoformat()} for m in q.messages]}


@app.get("/healthz")
def healthz():
    return {"ok": True}

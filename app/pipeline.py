"""The automatic part. Runs in background threads; no staff action is needed after an upload.

query letter uploaded -> read text -> split into points -> check locker -> render template
                      -> send WhatsApp + email in parallel -> record history and timings
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from . import classifier, llm, matcher, messaging, query_parser, storage
from .config import settings
from .db import session_scope
from .extraction import extract_text
from .models import AuditLog, Document, Message, Patient, QueryLetter, QueryPoint, utcnow
from .notify import email as email_notify
from .notify import whatsapp as wa_notify

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=settings.WORKER_THREADS, thread_name_prefix="pipeline")
_doc_locks: dict[int, threading.Lock] = {}
_doc_locks_guard = threading.Lock()
_query_locks: dict[int, threading.Lock] = {}

SYNC = False  # tests set this to run jobs inline


def submit(fn, *args, **kwargs):
    if SYNC:
        return fn(*args, **kwargs)
    fut = _executor.submit(_safe_run, fn, *args, **kwargs)
    return fut


def _safe_run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.exception("Background job %s failed", fn.__name__)


def _lock(table: dict, key: int) -> threading.Lock:
    with _doc_locks_guard:
        return table.setdefault(key, threading.Lock())


# ---------------------------------------------------------------- documents

def process_document(doc_id: int, recheck: bool = True) -> None:
    with _lock(_doc_locks, doc_id):
        with session_scope() as db:
            doc = db.get(Document, doc_id)
            if not doc or doc.status == "ready":
                return
            path = storage.path_for(doc.stored_name)
            name = doc.original_name
            manual_type = doc.doc_type if doc.type_source == "manual" else None
        text = extract_text(path)
        result = classifier.classify(text, name)
        with session_scope() as db:
            doc = db.get(Document, doc_id)
            if not doc:
                return
            doc.extracted_text = text
            doc.summary = result["summary"]
            doc.key_facts = result["key_facts"]
            if manual_type:
                doc.doc_type = manual_type
            else:
                doc.doc_type = result["doc_type"]
                doc.type_source = result["engine"]
            doc.status = "ready"
            patient_id = doc.patient_id
            promoted = None
            if (settings.AUTO_DETECT_QUERY_LETTERS and doc.doc_type == "query_letter"
                    and doc.type_source != "manual"):
                promoted = _promote_to_query(db, doc)
    if promoted:
        submit(process_query, promoted)
        return
    if recheck:
        recheck_open_queries(patient_id)


def _promote_to_query(db, doc: Document) -> int:
    """A query letter was uploaded through the documents box: treat it as a query letter."""
    q = QueryLetter(patient_id=doc.patient_id, original_name=doc.original_name, stored_name=doc.stored_name,
                    mime_type=doc.mime_type, sha256=doc.sha256, extracted_text=doc.extracted_text,
                    uploaded_by=doc.uploaded_by, uploaded_at=doc.uploaded_at, status="queued")
    db.add(q)
    db.add(AuditLog(action="query_letter_detected", patient_id=doc.patient_id,
                    target=f"document:{doc.id} -> query letter"))
    db.delete(doc)
    db.flush()
    return q.id


def ensure_documents_ready(patient_id: int) -> None:
    with session_scope() as db:
        pending = db.scalars(select(Document.id).where(Document.patient_id == patient_id,
                                                       Document.status != "ready")).all()
    for doc_id in pending:
        process_document(doc_id, recheck=False)


def recheck_open_queries(patient_id: int) -> None:
    """When new documents arrive, re-check queries that were waiting on the patient.
    Points now covered are marked as resolved; no new message is sent."""
    with session_scope() as db:
        queries = db.scalars(select(QueryLetter).where(QueryLetter.patient_id == patient_id,
                                                       QueryLetter.status.in_(["sent", "failed_send"]))).all()
        if not queries:
            return
        docs = _ready_docs(db, patient_id)
        for q in queries:
            open_pts = [p for p in q.points if p.decision == "needed"]
            if not open_pts:
                continue
            decisions, _ = matcher.match([_point_dict(p) for p in open_pts], docs)
            for p, d in zip(open_pts, decisions):
                if d["decision"] == "available":
                    p.decision = "available"
                    p.matched_document_ids = d["matched_document_ids"]
                    p.reason = "Received after the message was sent. " + (d["reason"] or "")
                    p.resolved_after_message = True
            if all(p.decision == "available" for p in q.points):
                q.status = "complete"
                db.add(AuditLog(action="query_complete", patient_id=patient_id, target=f"query:{q.id}"))


# ---------------------------------------------------------------- queries

def _ready_docs(db, patient_id: int) -> list[Document]:
    return db.scalars(select(Document).where(Document.patient_id == patient_id, Document.status == "ready",
                                             Document.doc_type != "query_letter")
                      .order_by(Document.uploaded_at)).all()


def _point_dict(p: QueryPoint) -> dict:
    return {"ref": p.ref, "insurer_text": p.insurer_text, "summary": p.summary, "kind": p.kind,
            "requested_types": p.requested_types or []}


def _set_status(query_id: int, status: str, **fields) -> None:
    with session_scope() as db:
        q = db.get(QueryLetter, query_id)
        if q:
            q.status = status
            for k, v in fields.items():
                setattr(q, k, v)


def process_query(query_id: int, send: bool = True) -> None:
    lock = _lock(_query_locks, query_id)
    if not lock.acquire(blocking=False):
        return  # already running
    try:
        _process_query(query_id, send)
    except Exception as exc:
        log.exception("Query %s failed", query_id)
        _set_status(query_id, "failed", error=f"Processing error: {exc}"[:1000])
    finally:
        lock.release()


def _process_query(query_id: int, send: bool) -> None:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    with session_scope() as db:
        q = db.get(QueryLetter, query_id)
        if not q:
            return
        q.status, q.error = "reading", ""
        path, patient_id, existing_text = storage.path_for(q.stored_name), q.patient_id, q.extracted_text

    text = existing_text or extract_text(path)
    timings["read_letter"] = round(time.perf_counter() - t0, 2)
    if len(text.strip()) < 20:
        _set_status(query_id, "failed", extracted_text=text, timings=timings,
                    error="Could not read text from this letter. Upload a clearer scan or a text PDF.")
        return

    _set_status(query_id, "analysing", extracted_text=text)
    ensure_documents_ready(patient_id)
    timings["documents_ready"] = round(time.perf_counter() - t0, 2)

    parsed = query_parser.parse(text)
    timings["parsed"] = round(time.perf_counter() - t0, 2)
    rules_header = query_parser.parse_rules(text) if parsed["engine"] == "llm" else parsed
    claim_ref = parsed.get("claim_reference") or ""
    if "[" in claim_ref:  # a redaction placeholder leaked back from the LLM
        claim_ref = rules_header.get("claim_reference", "")

    with session_scope() as db:
        docs = _ready_docs(db, patient_id)
        decisions, match_engine = matcher.match(parsed["points"], docs)
        timings["matched"] = round(time.perf_counter() - t0, 2)
        q = db.get(QueryLetter, query_id)
        q.points.clear()
        db.flush()
        for i, (p, d) in enumerate(zip(parsed["points"], decisions)):
            q.points.append(QueryPoint(position=i, ref=p["ref"], insurer_text=p["insurer_text"],
                                       summary=p.get("summary", ""), kind=p.get("kind", "document"),
                                       requested_types=p.get("requested_types", []), **d))
        q.insurer_name = (parsed.get("insurer_name") or "")[:200]
        q.claim_reference = claim_ref[:120]
        q.deadline = (parsed.get("deadline") or "")[:80]
        q.engine = f"parse:{parsed['engine']} match:{match_engine}" + (f" ({llm.model_name()})" if llm.enabled() else "")
        q.processed_at = utcnow()
        db.flush()
        if not q.points:
            q.status = "failed"
            q.error = "No query points were found in this letter. Check the text below and reprocess."
            q.timings = timings
            return
        needs_action = any(p.decision == "needed" for p in q.points)
        q.timings = timings
        if not send or (not needs_action and not settings.NOTIFY_WHEN_NOTHING_NEEDED):
            q.status = "no_action" if not needs_action else "ready"
            return
        q.status = "sending"

    send_messages(query_id, t0=t0, timings=timings)


def send_messages(query_id: int, t0: float | None = None, timings: dict | None = None) -> None:
    t0 = t0 or time.perf_counter()
    timings = dict(timings or {})
    with session_scope() as db:
        q = db.get(QueryLetter, query_id)
        patient = db.get(Patient, q.patient_id)
        docs_by_id = {d.id: d for d in patient.documents}
        msg = messaging.render(db, patient, q, docs_by_id)
        phone, email_addr, patient_id = patient.phone, patient.email, patient.id
        uploaded_at = q.uploaded_at

    # Send both channels in parallel
    results: dict = {}
    threads = [
        threading.Thread(target=lambda: results.__setitem__("whatsapp", wa_notify.send(phone, msg["body"]))),
        threading.Thread(target=lambda: results.__setitem__("email",
                                                            email_notify.send(email_addr, msg["subject"], msg["body"]))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    timings["sent"] = round(time.perf_counter() - t0, 2)

    with session_scope() as db:
        q = db.get(QueryLetter, query_id)
        statuses = []
        for channel in ("whatsapp", "email"):
            r = results.get(channel)
            if r is None:
                statuses.append("failed")
                db.add(Message(patient_id=patient_id, query_id=query_id, channel=channel, status="failed",
                               subject=msg["subject"] if channel == "email" else "", body=msg["body"],
                               error="Timed out"))
                continue
            statuses.append(r.status)
            db.add(Message(patient_id=patient_id, query_id=query_id, channel=channel, provider=r.provider,
                           recipient=r.recipient, subject=msg["subject"] if channel == "email" else "",
                           body=msg["body"], status=r.status, provider_message_id=r.provider_message_id,
                           error=r.error))
            db.add(AuditLog(action=f"auto_{channel}_{r.status}", patient_id=patient_id, target=f"query:{query_id}"))
        now = utcnow()
        q.sent_at = now
        q.seconds_to_send = round((now - uploaded_at).total_seconds(), 1)
        q.timings = timings
        if all(s == "failed" for s in statuses):
            q.status = "failed_send"
            q.error = "Both WhatsApp and email failed. See message history for details."
        else:
            q.status = "sent" if msg["needs_action"] else "no_action"
            failed = [c for c, s in zip(("WhatsApp", "Email"), statuses) if s == "failed"]
            q.error = f"{', '.join(failed)} failed. See message history." if failed else ""


def resume_pending() -> None:
    """Pick up jobs interrupted by a restart."""
    with session_scope() as db:
        doc_ids = db.scalars(select(Document.id).where(Document.status == "processing")).all()
        q_ids = db.scalars(select(QueryLetter.id).where(
            QueryLetter.status.in_(["queued", "reading", "analysing"]))).all()
    for d in doc_ids:
        submit(process_document, d)
    for qid in q_ids:
        submit(process_query, qid)

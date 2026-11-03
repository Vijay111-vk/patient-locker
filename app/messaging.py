"""Builds the patient message from a fixed template.

The LLM (or rules) only produce the per-item wording; the message itself is always the template with
placeholders filled in, so the output follows the template exactly."""
import re
from datetime import datetime

from sqlalchemy.orm import Session

from . import taxonomy
from .config import BASE_DIR, settings
from .models import Setting

TEMPLATE_FILES = {
    "message_template": BASE_DIR / "config" / "message_template.txt",
    "message_template_no_action": BASE_DIR / "config" / "message_template_no_action.txt",
    "email_subject": BASE_DIR / "config" / "email_subject.txt",
}

PLACEHOLDERS = {
    "patient_name": "Patient's full name",
    "patient_first_name": "Patient's first name",
    "patient_id": "Patient ID (e.g. PT-0001)",
    "insurer_name": "Insurer / TPA name from the letter (or profile)",
    "claim_number": "Claim number from the letter (or profile)",
    "hospital": "Hospital name",
    "needed_list": "Numbered list of what the patient must send, each with the reason",
    "needed_count": "How many items are needed",
    "available_list": "List of documents we already hold for this query",
    "deadline": "When to send it, e.g. 'by 30/10/2026', 'within 15 days of the insurer's letter', 'as soon as possible'",
    "portal_link": "Link to the patient's locker",
    "team_name": "Your team name (TEAM_NAME)",
    "team_contact": "How to reach the team (TEAM_CONTACT)",
    "date": "Today's date",
}


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


_PH_RE = re.compile(r"\{(\w+)\}")


def fill(template: str, ctx: dict) -> str:
    """Replace {placeholder}s; unknown placeholders and stray braces are left untouched."""
    return _PH_RE.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), template)


def get_template(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row and row.value.strip():
        return row.value
    return TEMPLATE_FILES[key].read_text(encoding="utf-8")


def set_template(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def friendly_deadline(raw: str) -> str:
    """Make the deadline read naturally after 'Please send the above ...'."""
    d = (raw or "").strip().rstrip(".")
    if not d:
        return "as soon as possible"
    m = re.match(r"(?i)(?:on or before|not later than|latest by|by)\s+(.+)", d)
    if m:
        return f"by {m.group(1)}"
    m = re.match(r"(?i)within\s+(\d+\s+(?:working\s+)?days)", d)
    if m:
        return f"within {m.group(1)} of the insurer's letter"
    if re.match(r"(?i)\d", d):
        return f"by {d}"
    return d


def build_needed_list(points) -> str:
    lines = []
    for i, p in enumerate([p for p in points if p.decision == "needed"], 1):
        item = (p.patient_request or p.summary or p.insurer_text).strip().rstrip(".")
        reason = (p.patient_reason or "").strip().rstrip(".")
        lines.append(f"{i}. {item}" + (f" - {reason}." if reason else "."))
    return "\n".join(lines)


def build_available_list(points, docs_by_id: dict) -> str:
    labels: list[str] = []
    for p in points:
        if p.decision != "available":
            continue
        for did in p.matched_document_ids or []:
            d = docs_by_id.get(did)
            if d:
                lbl = taxonomy.label(d.doc_type) if d.doc_type not in ("other", "unclassified") else d.original_name
                if lbl not in labels:
                    labels.append(lbl)
    return "\n".join(f"- {lbl}" for lbl in labels) if labels else "- (nothing from this query)"


def render(db: Session, patient, query, docs_by_id: dict) -> dict:
    needed = [p for p in query.points if p.decision == "needed"]
    ctx = _SafeDict(
        patient_name=patient.full_name,
        patient_first_name=patient.full_name.split()[0] if patient.full_name else "",
        patient_id=patient.patient_code,
        insurer_name=query.insurer_name or patient.insurer or "your insurer",
        claim_number=query.claim_reference or patient.claim_number or "(claim number not given)",
        hospital=patient.hospital or "the hospital",
        needed_list=build_needed_list(query.points),
        needed_count=str(len(needed)),
        available_list=build_available_list(query.points, docs_by_id),
        deadline=friendly_deadline(query.deadline),
        portal_link=f"{settings.PORTAL_BASE_URL}/login",
        team_name=settings.TEAM_NAME,
        team_contact=settings.TEAM_CONTACT,
        date=datetime.now().strftime("%d %b %Y"),
    )
    key = "message_template" if needed else "message_template_no_action"
    body = fill(get_template(db, key), ctx).strip()
    if needed:
        subject = fill(get_template(db, "email_subject"), ctx).strip()
    else:
        subject = f"Update on your claim {ctx['claim_number']}: no action needed"
    return {"subject": subject.splitlines()[0][:250], "body": body, "needs_action": bool(needed)}

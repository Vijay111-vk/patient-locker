"""Helpers for handling patient data carefully."""
import re

AADHAAR_RE = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
ACCOUNT_RE = re.compile(r"(?i)(a/?c(?:count)?\s*(?:no|number)?\.?\s*[:\-]?\s*)(\d{9,18})")


def redact_identifiers(text: str) -> str:
    """Remove ID numbers before text leaves our system (e.g. to an LLM API).
    Document *type* words (\"Aadhaar\", \"PAN\") are kept so classification still works."""
    if not text:
        return text
    text = AADHAAR_RE.sub("[ID-NUMBER]", text)
    text = PAN_RE.sub("[PAN-NUMBER]", text)
    text = ACCOUNT_RE.sub(lambda m: m.group(1) + "[ACCOUNT-NUMBER]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    return text


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 4:
        return "—" if not digits else "••••"
    return "•" * max(0, len(digits) - 4) + digits[-4:]


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email or "—"
    name, domain = email.split("@", 1)
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}{'•' * max(3, len(name) - len(keep))}@{domain}"


def normalize_phone(phone: str, default_cc: str = "91") -> str:
    """Return E.164 (+<digits>) or empty string."""
    if not phone:
        return ""
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 10:
        return f"+{default_cc}{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+{default_cc}{digits[1:]}"
    if len(digits) == 12 and digits.startswith(default_cc):
        return "+" + digits
    return "+" + digits if digits else ""

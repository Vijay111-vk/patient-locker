"""WhatsApp sending. WHATSAPP_PROVIDER=twilio | meta | console."""
import logging

import httpx

from ..config import settings
from ..privacy import mask_phone, normalize_phone
from . import SendResult

log = logging.getLogger(__name__)
TWILIO_MAX = 1550  # Twilio limit is 1600 chars per WhatsApp message; leave room for "(1/2)"


def configured() -> tuple[bool, str]:
    p = settings.WHATSAPP_PROVIDER
    if p == "twilio":
        ok = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM)
        return ok, "Twilio" + ("" if ok else " (missing TWILIO_* settings)")
    if p == "meta":
        ok = bool(settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID)
        return ok, "Meta WhatsApp Cloud API" + ("" if ok else " (missing META_* settings)")
    return False, "Console (messages are logged, not sent)"


def recipient_for(patient_phone: str) -> str:
    return normalize_phone(settings.TEST_RECIPIENT_PHONE or patient_phone, settings.DEFAULT_COUNTRY_CODE)


def send(patient_phone: str, body: str) -> SendResult:
    to = recipient_for(patient_phone)
    provider = settings.WHATSAPP_PROVIDER
    if not to:
        return SendResult("failed", provider, "", error="No phone number on the patient profile")
    ok, _ = configured()
    if provider not in ("twilio", "meta") or not ok:
        log.info("[whatsapp:console] to=%s chars=%d", mask_phone(to), len(body))
        return SendResult("simulated", "console", to)
    try:
        return _twilio(to, body) if provider == "twilio" else _meta(to, body)
    except httpx.HTTPError as exc:
        return SendResult("failed", provider, to, error=f"Network error: {exc}")


def _chunks(body: str, size: int) -> list[str]:
    if len(body) <= size:
        return [body]
    parts, current = [], ""
    for para in body.split("\n"):
        if len(current) + len(para) + 1 > size and current:
            parts.append(current.rstrip())
            current = ""
        while len(para) > size:
            parts.append(para[:size])
            para = para[size:]
        current += para + "\n"
    if current.strip():
        parts.append(current.rstrip())
    n = len(parts)
    return [f"({i}/{n})\n{p}" for i, p in enumerate(parts, 1)]


def _twilio(to: str, body: str) -> SendResult:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    from_ = settings.TWILIO_WHATSAPP_FROM
    from_ = from_ if from_.startswith("whatsapp:") else f"whatsapp:{from_}"
    sids = []
    for part in _chunks(body, TWILIO_MAX):
        r = httpx.post(url, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                       data={"From": from_, "To": f"whatsapp:{to}", "Body": part}, timeout=30)
        if r.status_code >= 400:
            try:
                err = r.json().get("message", r.text)
            except ValueError:
                err = r.text
            return SendResult("failed", "twilio", to, provider_message_id=",".join(sids),
                              error=f"Twilio {r.status_code}: {err[:300]}")
        sids.append(r.json().get("sid", ""))
    return SendResult("sent", "twilio", to, provider_message_id=",".join(sids))


def _meta(to: str, body: str) -> SendResult:
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{settings.META_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
    to_digits = to.lstrip("+")
    ids = []
    if settings.META_TEMPLATE_NAME:
        # Business-initiated messages outside the 24h window must use an approved template.
        # Template params may not contain newlines, so the message is flattened into one parameter.
        flat = " | ".join(line.strip() for line in body.splitlines() if line.strip())[:1000]
        payload = {"messaging_product": "whatsapp", "to": to_digits, "type": "template",
                   "template": {"name": settings.META_TEMPLATE_NAME,
                                "language": {"code": settings.META_TEMPLATE_LANG},
                                "components": [{"type": "body", "parameters": [{"type": "text", "text": flat}]}]}}
        r = httpx.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            return SendResult("failed", "meta", to, error=f"Meta {r.status_code}: {r.text[:300]}")
        ids += [m.get("id", "") for m in r.json().get("messages", [])]
        # Then send the full text (delivered when the conversation window is open).
    for part in _chunks(body, 4000):
        r = httpx.post(url, headers=headers, timeout=30,
                       json={"messaging_product": "whatsapp", "to": to_digits, "type": "text",
                             "text": {"preview_url": False, "body": part}})
        if r.status_code >= 400:
            if ids:  # the template went through; the free-text follow-up needs an open window
                return SendResult("sent", "meta", to, provider_message_id=",".join(ids),
                                  error=f"Template sent; full text not delivered: {r.text[:200]}")
            return SendResult("failed", "meta", to, error=f"Meta {r.status_code}: {r.text[:300]}")
        ids += [m.get("id", "") for m in r.json().get("messages", [])]
    return SendResult("sent", "meta", to, provider_message_id=",".join(ids))

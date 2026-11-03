"""Email sending over SMTP (works with Gmail app passwords, SendGrid, Brevo, SES, Mailgun, ...).
EMAIL_PROVIDER=smtp | console."""
import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from ..config import settings
from ..privacy import mask_email
from . import SendResult

log = logging.getLogger(__name__)


def configured() -> tuple[bool, str]:
    if settings.EMAIL_PROVIDER == "smtp":
        ok = bool(settings.SMTP_HOST and settings.EMAIL_FROM)
        return ok, f"SMTP ({settings.SMTP_HOST or 'no host'})" + ("" if ok else " (missing SMTP_HOST / EMAIL_FROM)")
    return False, "Console (emails are logged, not sent)"


def recipient_for(patient_email: str) -> str:
    return (settings.TEST_RECIPIENT_EMAIL or patient_email or "").strip()


def _html(body: str, team: str) -> str:
    lines = []
    for line in body.splitlines():
        esc = html.escape(line)
        lines.append(f"<p style='margin:0 0 6px 0'>{esc}</p>" if esc.strip() else "<br>")
    return (f"<div style='font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#1d2a2c;"
            f"max-width:620px'>{''.join(lines)}<hr style='border:none;border-top:1px solid #ddd;margin:18px 0'>"
            f"<p style='font-size:12px;color:#667'>Sent by {html.escape(team)}. This email contains information "
            f"about your health insurance claim. If you received it by mistake, please delete it.</p></div>")


def send(patient_email: str, subject: str, body: str) -> SendResult:
    to = recipient_for(patient_email)
    if not to or "@" not in to:
        return SendResult("failed", settings.EMAIL_PROVIDER, to, error="No email address on the patient profile")
    ok, _ = configured()
    if settings.EMAIL_PROVIDER != "smtp" or not ok:
        log.info("[email:console] to=%s subject=%r", mask_email(to), subject)
        return SendResult("simulated", "console", to)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg_id = make_msgid(domain=settings.EMAIL_FROM.split("@")[-1].strip(">"))
    msg["Message-ID"] = msg_id
    msg.set_content(body)
    msg.add_alternative(_html(body, settings.TEAM_NAME), subtype="html")
    try:
        ctx = ssl.create_default_context()
        if settings.SMTP_USE_SSL or settings.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ctx, timeout=30) as s:
                _login_send(s, msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as s:
                s.ehlo()
                if s.has_extn("starttls"):
                    s.starttls(context=ctx)
                    s.ehlo()
                _login_send(s, msg)
        return SendResult("sent", "smtp", to, provider_message_id=msg_id)
    except Exception as exc:
        return SendResult("failed", "smtp", to, error=f"SMTP error: {exc}"[:400])


def _login_send(s, msg):
    if settings.SMTP_USER:
        s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    s.send_message(msg)

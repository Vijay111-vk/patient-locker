"""Central configuration, read from environment variables (and .env if present)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # Core
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    PORTAL_BASE_URL: str = os.getenv("PORTAL_BASE_URL", "http://localhost:8000").rstrip("/")
    SECURE_COOKIES: bool = _bool("SECURE_COOKIES", False)
    SESSION_HOURS: int = int(os.getenv("SESSION_HOURS", "8"))
    API_KEY: str = os.getenv("API_KEY", "")  # for the machine-to-machine upload API
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    DISPLAY_TZ: str = os.getenv("DISPLAY_TZ", "Asia/Kolkata")
    AUTO_DETECT_QUERY_LETTERS: bool = _bool("AUTO_DETECT_QUERY_LETTERS", True)

    # Organisation details used in messages
    TEAM_NAME: str = os.getenv("TEAM_NAME", "Claims Support Team")
    TEAM_CONTACT: str = os.getenv("TEAM_CONTACT", "please contact our claims team")

    # LLM: anthropic | openai | gemini | none
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "none").strip().lower()
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    REDACT_IDS_FOR_LLM: bool = _bool("REDACT_IDS_FOR_LLM", True)

    # WhatsApp: twilio | meta | console
    WHATSAPP_PROVIDER: str = os.getenv("WHATSAPP_PROVIDER", "console").strip().lower()
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "+14155238886")
    META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
    META_PHONE_NUMBER_ID: str = os.getenv("META_PHONE_NUMBER_ID", "")
    META_API_VERSION: str = os.getenv("META_API_VERSION", "v21.0")
    META_TEMPLATE_NAME: str = os.getenv("META_TEMPLATE_NAME", "")
    META_TEMPLATE_LANG: str = os.getenv("META_TEMPLATE_LANG", "en")

    # Email: smtp | console
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "console").strip().lower()
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_SSL: bool = _bool("SMTP_USE_SSL", False)
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")

    # Testing / demo helpers
    TEST_RECIPIENT_PHONE: str = os.getenv("TEST_RECIPIENT_PHONE", "")
    TEST_RECIPIENT_EMAIL: str = os.getenv("TEST_RECIPIENT_EMAIL", "")
    NOTIFY_WHEN_NOTHING_NEEDED: bool = _bool("NOTIFY_WHEN_NOTHING_NEEDED", True)
    DEFAULT_COUNTRY_CODE: str = os.getenv("DEFAULT_COUNTRY_CODE", "91")
    OCR_ENABLED: bool = _bool("OCR_ENABLED", True)
    WORKER_THREADS: int = int(os.getenv("WORKER_THREADS", "4"))

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.DATA_DIR / 'locker.db'}"

    @property
    def files_dir(self) -> Path:
        p = self.DATA_DIR / "files"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))  # admin | staff | patient
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    dob: Mapped[str] = mapped_column(String(20), default="")
    gender: Mapped[str] = mapped_column(String(20), default="")
    hospital: Mapped[str] = mapped_column(String(200), default="")
    insurer: Mapped[str] = mapped_column(String(200), default="")
    policy_number: Mapped[str] = mapped_column(String(80), default="")
    claim_number: Mapped[str] = mapped_column(String(80), default="")
    admission_date: Mapped[str] = mapped_column(String(20), default="")
    discharge_date: Mapped[str] = mapped_column(String(20), default="")
    diagnosis: Mapped[str] = mapped_column(String(300), default="")
    preferred_language: Mapped[str] = mapped_column(String(20), default="English")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="patient", cascade="all, delete-orphan",
                                                       order_by="Document.uploaded_at.desc()")
    queries: Mapped[list["QueryLetter"]] = relationship(back_populates="patient", cascade="all, delete-orphan",
                                                        order_by="QueryLetter.uploaded_at.desc()")
    messages: Mapped[list["Message"]] = relationship(back_populates="patient", cascade="all, delete-orphan",
                                                     order_by="Message.created_at.desc()")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(50), default="unclassified")
    type_source: Mapped[str] = mapped_column(String(20), default="pending")  # pending|llm|rules|manual
    summary: Mapped[str] = mapped_column(Text, default="")
    key_facts: Mapped[dict] = mapped_column(JSON, default=dict)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing|ready|failed
    uploaded_by: Mapped[str] = mapped_column(String(80), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="documents")


class QueryLetter(Base):
    __tablename__ = "query_letters"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    insurer_name: Mapped[str] = mapped_column(String(200), default="")
    claim_reference: Mapped[str] = mapped_column(String(120), default="")
    deadline: Mapped[str] = mapped_column(String(80), default="")
    # queued | reading | analysing | sending | sent | no_action | complete | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    engine: Mapped[str] = mapped_column(String(40), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str] = mapped_column(String(80), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seconds_to_send: Mapped[float | None] = mapped_column(Float, nullable=True)
    timings: Mapped[dict] = mapped_column(JSON, default=dict)

    patient: Mapped[Patient] = relationship(back_populates="queries")
    points: Mapped[list["QueryPoint"]] = relationship(back_populates="query", cascade="all, delete-orphan",
                                                      order_by="QueryPoint.position")
    messages: Mapped[list["Message"]] = relationship(back_populates="query", order_by="Message.created_at")

    @property
    def needed_points(self):
        return [p for p in self.points if p.decision == "needed"]

    @property
    def available_points(self):
        return [p for p in self.points if p.decision == "available"]


class QueryPoint(Base):
    __tablename__ = "query_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("query_letters.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str] = mapped_column(String(20), default="")
    insurer_text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="document")  # document | clarification
    requested_types: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(20), default="pending")  # available | needed | pending
    matched_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    patient_request: Mapped[str] = mapped_column(Text, default="")
    patient_reason: Mapped[str] = mapped_column(Text, default="")
    resolved_after_message: Mapped[bool] = mapped_column(Boolean, default=False)

    query: Mapped[QueryLetter] = relationship(back_populates="points")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int | None] = mapped_column(ForeignKey("query_letters.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))  # whatsapp | email
    provider: Mapped[str] = mapped_column(String(20), default="")
    recipient: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # sent | simulated | failed
    provider_message_id: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="messages")
    query: Mapped[QueryLetter | None] = relationship(back_populates="messages")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(80), default="system")
    role: Mapped[str] = mapped_column(String(20), default="system")
    action: Mapped[str] = mapped_column(String(80))
    patient_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(200), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, ForeignKey, Enum, JSON, Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# NOTE: IDs are stored as String(36) UUIDs rather than the native Postgres UUID
# type. This is a deliberate simplicity/portability trade-off: it keeps the
# schema testable against SQLite in unit tests while still working fine on
# Postgres in production (just without the native uuid column type / index
# compaction benefits). Documented as a known trade-off in ARCHITECTURE.md.


def gen_uuid():
    return str(uuid.uuid4())


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"


class DocumentRole(str, enum.Enum):
    QUESTION_PAPER = "question_paper"
    ANSWER_KEY = "answer_key"
    UNKNOWN = "unknown"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="owner")


class DocumentGroup(Base):
    """Groups related documents, e.g. Question Paper + Answer Key."""
    __tablename__ = "document_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="group")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("document_groups.id"), nullable=True)

    original_filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str] = mapped_column(String(20))  # pdf, jpg, png
    file_size_bytes: Mapped[int] = mapped_column(Integer)

    role: Mapped[DocumentRole] = mapped_column(Enum(DocumentRole), default=DocumentRole.UNKNOWN)
    status: Mapped[ProcessingStatus] = mapped_column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="documents")
    group: Mapped["DocumentGroup | None"] = relationship(back_populates="documents")
    pages: Mapped[list["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(back_populates="source_document", cascade="all, delete-orphan")


class Page(Base):
    """One page/image extracted from a document, plus raw AI/OCR output for traceability."""
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # extracted text / OCR output
    raw_ai_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # full LLM response for audit
    processed: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped["Document"] = relationship(back_populates="pages")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))

    question_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # mcq, short_answer, etc.
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # list[str] or list[{label, text}]

    source_pages: Mapped[list] = mapped_column(JSON, default=list)  # e.g. [3, 4]
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    image_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)

    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    source_document: Mapped["Document"] = relationship(back_populates="questions")
    answer: Mapped["Answer | None"] = relationship(back_populates="question", uselist=False, cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), unique=True)

    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped["Question"] = relationship(back_populates="answer")

from datetime import datetime
from pydantic import BaseModel, EmailStr


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Documents ----------
class DocumentOut(BaseModel):
    id: str
    original_filename: str
    file_type: str
    status: str
    role: str
    page_count: int | None
    group_id: str | None
    created_at: datetime
    error_message: str | None = None

    class Config:
        from_attributes = True


class DocumentStatusOut(BaseModel):
    id: str
    status: str
    error_message: str | None = None
    total_questions: int = 0
    questions_needing_review: int = 0


class DocumentGroupCreate(BaseModel):
    name: str
    document_ids: list[str] = []


class DocumentGroupOut(BaseModel):
    id: str
    name: str
    document_ids: list[str]

    class Config:
        from_attributes = True


# ---------- Questions ----------
class AnswerOut(BaseModel):
    answer_text: str | None
    is_matched: bool
    match_confidence: float
    source_page: int | None = None

    class Config:
        from_attributes = True


class QuestionOut(BaseModel):
    id: str
    question_number: str | None
    question_text: str
    question_type: str | None
    options: list | None
    source_pages: list
    has_image: bool
    extraction_confidence: float
    needs_review: bool
    review_reason: str | None
    answer: AnswerOut | None = None

    class Config:
        from_attributes = True


class QuestionListOut(BaseModel):
    total: int
    items: list[QuestionOut]


class ReviewItemOut(BaseModel):
    id: str
    question_number: str | None
    question_text: str
    extraction_confidence: float
    review_reason: str | None
    source_pages: list

    class Config:
        from_attributes = True

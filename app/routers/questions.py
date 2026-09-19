from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Question, Document
from app.schemas import QuestionOut, QuestionListOut, ReviewItemOut
from app.auth import get_current_user

router = APIRouter(tags=["questions"])


def _owned_document_ids(db: Session, user_id: str) -> list[str]:
    return [d.id for d in db.query(Document.id).filter(Document.owner_id == user_id).all()]


@router.get("/documents/{document_id}/questions", response_model=QuestionListOut)
def list_questions_for_document(
    document_id: str,
    needs_review: bool | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    q = db.query(Question).filter(Question.source_document_id == document_id)
    if needs_review is not None:
        q = q.filter(Question.needs_review.is_(needs_review))

    items = q.all()
    return QuestionListOut(total=len(items), items=items)


@router.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(question_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    owned_ids = _owned_document_ids(db, current_user.id)
    question = db.query(Question).filter(
        Question.id == question_id, Question.source_document_id.in_(owned_ids)
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


@router.get("/documents/{document_id}/review-items", response_model=list[ReviewItemOut])
def list_review_items(document_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return db.query(Question).filter(
        Question.source_document_id == document_id, Question.needs_review.is_(True)
    ).all()

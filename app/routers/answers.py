from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Question, Document, Answer
from app.schemas import AnswerOut
from app.auth import get_current_user

router = APIRouter(tags=["answers"])


@router.get("/documents/{document_id}/answers", response_model=list[AnswerOut])
def list_answers_for_document(document_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    answers = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .filter(Question.source_document_id == document_id)
        .all()
    )
    return answers


@router.get("/questions/{question_id}/answer", response_model=AnswerOut)
def get_answer_for_question(question_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    question = (
        db.query(Question)
        .join(Document, Question.source_document_id == Document.id)
        .filter(Question.id == question_id, Document.owner_id == current_user.id)
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if not question.answer:
        raise HTTPException(status_code=404, detail="No answer identified for this question")
    return question.answer

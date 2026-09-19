import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentGroup, ProcessingStatus, Question
from app.schemas import DocumentOut, DocumentStatusOut, DocumentGroupCreate, DocumentGroupOut
from app.auth import get_current_user
from app.config import settings
from app.tasks.worker import process_document_task

router = APIRouter(prefix="/documents", tags=["documents"])


def _validate_upload(file: UploadFile):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: .{ext}. Allowed: {settings.allowed_extensions_list}",
        )
    return ext


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    group_id: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ext = _validate_upload(file)

    os.makedirs(settings.storage_dir, exist_ok=True)
    file_id = str(uuid.uuid4())
    storage_path = os.path.join(settings.storage_dir, f"{file_id}.{ext}")

    contents = file.file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_size_mb}MB limit",
        )

    with open(storage_path, "wb") as f:
        f.write(contents)

    if group_id:
        group = db.query(DocumentGroup).filter(
            DocumentGroup.id == group_id, DocumentGroup.owner_id == current_user.id
        ).first()
        if not group:
            raise HTTPException(status_code=404, detail="Document group not found")

    doc = Document(
        owner_id=current_user.id,
        group_id=group_id,
        original_filename=file.filename,
        storage_path=storage_path,
        file_type=ext,
        file_size_bytes=len(contents),
        status=ProcessingStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Kick off async processing - does not block the client
    process_document_task.delay(doc.id)

    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return db.query(Document).filter(Document.owner_id == current_user.id).all()


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doc = db.query(Document).filter(
        Document.id == document_id, Document.owner_id == current_user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/status", response_model=DocumentStatusOut)
def get_document_status(document_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doc = db.query(Document).filter(
        Document.id == document_id, Document.owner_id == current_user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    total = db.query(Question).filter(Question.source_document_id == doc.id).count()
    needing_review = db.query(Question).filter(
        Question.source_document_id == doc.id, Question.needs_review.is_(True)
    ).count()

    return DocumentStatusOut(
        id=doc.id,
        status=doc.status,
        error_message=doc.error_message,
        total_questions=total,
        questions_needing_review=needing_review,
    )


# ---------- Document Groups (e.g. Question Paper + Answer Key) ----------

@router.post("/groups", response_model=DocumentGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: DocumentGroupCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    group = DocumentGroup(name=payload.name, owner_id=current_user.id)
    db.add(group)
    db.flush()

    if payload.document_ids:
        docs = db.query(Document).filter(
            Document.id.in_(payload.document_ids), Document.owner_id == current_user.id
        ).all()
        for d in docs:
            d.group_id = group.id

    db.commit()
    db.refresh(group)
    doc_ids = [d.id for d in db.query(Document).filter(Document.group_id == group.id).all()]
    return DocumentGroupOut(id=group.id, name=group.name, document_ids=doc_ids)


@router.get("/groups/{group_id}", response_model=DocumentGroupOut)
def get_group(group_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    group = db.query(DocumentGroup).filter(
        DocumentGroup.id == group_id, DocumentGroup.owner_id == current_user.id
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    doc_ids = [d.id for d in db.query(Document).filter(Document.group_id == group.id).all()]
    return DocumentGroupOut(id=group.id, name=group.name, document_ids=doc_ids)

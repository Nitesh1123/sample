"""
Main document-processing pipeline, run asynchronously via Celery.

Flow for process_document_task(document_id):
  1. Load Document row, mark status=PROCESSING.
  2. Render to page images (ocr_service).
  3. For each page: call extraction_service.extract_page() -> persist a Page
     row with raw_ai_response for auditability. Collect page_type + questions
     + answer_key_entries.
  4. Determine document role (question_paper vs answer_key) from the
     majority page_type seen.
  5. Stitch multi-page questions (extraction_service.stitch_multi_page_questions)
     and persist Question rows. Any question below CONFIDENCE_REVIEW_THRESHOLD
     is flagged needs_review=True.
  6. Collect answer_key_entries found in THIS document, plus (if this document
     belongs to a group) answer_key_entries from sibling documents in the same
     group whose role is ANSWER_KEY, then run answer_key_service.match_answers_to_questions
     and persist Answer rows.
  7. Mark status=COMPLETED (or PARTIALLY_COMPLETED if some pages failed, or
     FAILED if nothing could be extracted).

TODO (Copilot):
  - Wire in retry logic per-page (a single flaky page shouldn't fail the whole doc).
  - If a document belongs to a group and its sibling (the answer key) hasn't
    finished processing yet, you may want a second, lightweight task that
    re-runs answer matching once both documents in the group are COMPLETED.
    A simple approach: after finishing a document, check if all group siblings
    are COMPLETED, and if so, enqueue a `match_group_answers_task(group_id)`.
  - Add structured logging (the print() calls below are placeholders).
"""
import os

from app.database import SessionLocal
from app.models import Document, Page, Question, Answer, ProcessingStatus, DocumentRole
from app.services.ocr_service import render_document_to_page_images
from app.services.extraction_service import extract_page, stitch_multi_page_questions
from app.services.answer_key_service import match_answers_to_questions
from app.tasks.celery_app import celery_app

CONFIDENCE_REVIEW_THRESHOLD = 0.6


def _match_and_persist_answers_for_document(db, doc: Document, stitched: list[dict]) -> None:
    own_answer_entries = [
        entry for r in db.query(Page).filter(Page.document_id == doc.id).all()
        for entry in (r.raw_ai_response or {}).get("answer_key_entries", [])
    ]

    sibling_answer_entries = []
    if doc.group_id:
        siblings = db.query(Document).filter(
            Document.group_id == doc.group_id,
            Document.id != doc.id,
            Document.role == DocumentRole.ANSWER_KEY,
            Document.status == ProcessingStatus.COMPLETED,
        ).all()
        for sib in siblings:
            sib_pages = db.query(Page).filter(Page.document_id == sib.id).all()
            for p in sib_pages:
                if p.raw_ai_response:
                    sibling_answer_entries.extend(p.raw_ai_response.get("answer_key_entries", []))

    all_answer_entries = own_answer_entries + sibling_answer_entries
    answer_matches = match_answers_to_questions(stitched, all_answer_entries)

    for idx, q in enumerate(stitched):
        existing_question = db.query(Question).filter(
            Question.source_document_id == doc.id,
            Question.question_number == q.get("question_number"),
            Question.question_text == q.get("question_text", ""),
        ).order_by(Question.created_at.desc()).first()
        if not existing_question:
            existing_question = db.query(Question).filter(Question.source_document_id == doc.id).offset(idx).first()
        if not existing_question:
            continue

        match = answer_matches.get(idx, {"is_matched": False, "answer_text": None, "match_confidence": 0.0})
        if existing_question.answer:
            existing_question.answer.answer_text = match["answer_text"]
            existing_question.answer.match_confidence = match["match_confidence"]
            existing_question.answer.is_matched = match["is_matched"]
        else:
            answer_row = Answer(
                question_id=existing_question.id,
                answer_text=match["answer_text"],
                match_confidence=match["match_confidence"],
                is_matched=match["is_matched"],
            )
            db.add(answer_row)


def _queue_group_answer_match_if_ready(db, doc: Document) -> None:
    if not doc.group_id:
        return
    siblings = db.query(Document).filter(Document.group_id == doc.group_id).all()
    if not siblings:
        return
    if all(s.status == ProcessingStatus.COMPLETED for s in siblings):
        match_group_answers_task.delay(doc.group_id)


@celery_app.task(name="app.tasks.worker.match_group_answers_task", bind=True, max_retries=2)
def match_group_answers_task(self, group_id: str):
    db = SessionLocal()
    try:
        group_docs = db.query(Document).filter(Document.group_id == group_id).all()
        if not group_docs or any(doc.status != ProcessingStatus.COMPLETED for doc in group_docs):
            return

        question_doc = next((d for d in group_docs if d.role == DocumentRole.QUESTION_PAPER), None)
        answer_doc = next((d for d in group_docs if d.role == DocumentRole.ANSWER_KEY), None)
        if not question_doc or not answer_doc:
            return

        question_rows = db.query(Question).filter(Question.source_document_id == question_doc.id).all()
        stitched = [
            {
                "question_number": q.question_number,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": q.options,
                "has_image": q.has_image,
                "source_pages": q.source_pages,
                "confidence": q.extraction_confidence,
            }
            for q in question_rows
        ]
        answer_entries = []
        for page in db.query(Page).filter(Page.document_id == answer_doc.id).all():
            if page.raw_ai_response:
                answer_entries.extend(page.raw_ai_response.get("answer_key_entries", []))
        answer_matches = match_answers_to_questions(stitched, answer_entries)
        for idx, q in enumerate(question_rows):
            match = answer_matches.get(idx, {"is_matched": False, "answer_text": None, "match_confidence": 0.0})
            if q.answer:
                q.answer.answer_text = match["answer_text"]
                q.answer.match_confidence = match["match_confidence"]
                q.answer.is_matched = match["is_matched"]
            else:
                db.add(Answer(
                    question_id=q.id,
                    answer_text=match["answer_text"],
                    match_confidence=match["match_confidence"],
                    is_matched=match["is_matched"],
                ))
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker.process_document_task", bind=True, max_retries=2)
def process_document_task(self, document_id: str):
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            print(f"[process_document_task] Document {document_id} not found")
            return

        doc.status = ProcessingStatus.PROCESSING
        db.commit()

        pages_dir = os.path.join(os.path.dirname(doc.storage_path), f"{doc.id}_pages")
        try:
            page_image_paths = render_document_to_page_images(doc.storage_path, doc.file_type, pages_dir)
        except Exception as e:
            doc.status = ProcessingStatus.FAILED
            doc.error_message = f"Failed to render document to pages: {e}"
            db.commit()
            return

        doc.page_count = len(page_image_paths)
        db.commit()

        page_results = []
        failed_pages = 0

        for i, image_path in enumerate(page_image_paths, start=1):
            page_row = Page(document_id=doc.id, page_number=i, image_path=image_path)
            try:
                result = extract_page(image_path)
                page_row.raw_ai_response = result
                page_row.processed = True
                page_results.append(result)
            except Exception as e:
                failed_pages += 1
                page_row.processed = False
                page_row.raw_ai_response = {"error": str(e)}
                page_results.append({"page_type": "other", "questions": [], "answer_key_entries": []})
                print(f"[process_document_task] Page {i} of {doc.id} failed: {e}")
            db.add(page_row)

        db.commit()

        page_types = [r.get("page_type", "other") for r in page_results]
        if page_types.count("answer_key") > len(page_types) / 2:
            doc.role = DocumentRole.ANSWER_KEY
        elif page_types.count("questions") > 0:
            doc.role = DocumentRole.QUESTION_PAPER
        db.commit()

        stitched = stitch_multi_page_questions(page_results)
        for idx, q in enumerate(stitched):
            confidence = q.get("confidence", 0.5)
            needs_review = confidence < CONFIDENCE_REVIEW_THRESHOLD
            review_reason = None
            if needs_review:
                review_reason = f"Low extraction confidence ({confidence:.2f})"

            question_row = Question(
                source_document_id=doc.id,
                question_number=q.get("question_number"),
                question_text=q.get("question_text", ""),
                question_type=q.get("question_type"),
                options=q.get("options"),
                source_pages=q.get("source_pages", []),
                has_image=q.get("has_image", False),
                extraction_confidence=confidence,
                needs_review=needs_review,
                review_reason=review_reason,
            )
            db.add(question_row)
            db.flush()

        db.commit()
        _match_and_persist_answers_for_document(db, doc, stitched)
        db.commit()

        if failed_pages == 0 and len(stitched) > 0:
            doc.status = ProcessingStatus.COMPLETED
        elif len(stitched) > 0:
            doc.status = ProcessingStatus.PARTIALLY_COMPLETED
            doc.error_message = f"{failed_pages} of {len(page_image_paths)} pages failed to process"
        else:
            doc.status = ProcessingStatus.FAILED
            doc.error_message = "No questions could be extracted from this document"

        db.commit()

        _queue_group_answer_match_if_ready(db, doc)
        db.commit()

    finally:
        db.close()

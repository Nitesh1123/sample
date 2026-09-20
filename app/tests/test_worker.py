from unittest.mock import patch

from app.models import Document, ProcessingStatus
from app.tasks import worker
from app.tests.conftest import TestingSessionLocal


def test_answer_key_only_document_is_completed(monkeypatch, tmp_path):
    db = TestingSessionLocal()
    document = Document(
        id="answer-key-only-document",
        owner_id="test-owner",
        original_filename="sample_answer_key.pdf",
        storage_path=str(tmp_path / "sample_answer_key.pdf"),
        file_type="pdf",
        file_size_bytes=1,
    )
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()

    monkeypatch.setattr(worker, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(worker, "render_document_to_page_images", lambda *args: ["page-1.png"])
    monkeypatch.setattr(
        worker,
        "extract_page",
        lambda _path: {
            "page_type": "answer_key",
            "questions": [],
            "answer_key_entries": [
                {"question_number": "1", "answer_text": "B", "confidence": 0.98}
            ],
        },
    )
    with patch.object(worker.match_group_answers_task, "delay"):
        worker.process_document_task.apply(args=[document_id]).get()

    db = TestingSessionLocal()
    refreshed = db.query(Document).filter(Document.id == document_id).one()
    assert refreshed.status == ProcessingStatus.COMPLETED
    assert refreshed.error_message is None
    db.close()
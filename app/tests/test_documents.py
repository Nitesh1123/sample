import io
from unittest.mock import patch


def test_upload_rejects_bad_file_type(client, auth_headers):
    resp = client.post(
        "/documents/upload",
        files={"file": ("malware.exe", io.BytesIO(b"fake"), "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 415


def test_upload_pdf_triggers_async_processing(client, auth_headers, tmp_path):
    with patch("app.routers.documents.process_document_task.delay") as mock_delay, \
         patch("app.routers.documents.settings") as mock_settings:
        mock_settings.storage_dir = str(tmp_path)
        mock_settings.allowed_extensions_list = ["pdf", "jpg", "jpeg", "png"]
        mock_settings.max_upload_size_mb = 25

        resp = client.post(
            "/documents/upload",
            files={"file": ("questions.pdf", io.BytesIO(b"%PDF-1.4 fake content"), "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["original_filename"] == "questions.pdf"
        mock_delay.assert_called_once()


def test_list_documents_only_returns_own(client, auth_headers):
    resp = client.get("/documents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_nonexistent_document_status_404(client, auth_headers):
    resp = client.get("/documents/does-not-exist/status", headers=auth_headers)
    assert resp.status_code == 404

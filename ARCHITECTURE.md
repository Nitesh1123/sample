# Architecture

## Overview
```
Client -> FastAPI (auth, upload, query) -> Postgres (metadata + structured output)
                |
                v
          Celery task queued (Redis broker)
                |
                v
        Celery worker: OCR/render -> vision-LLM extraction per page
                -> stitch multi-page questions -> answer-key matching
                -> persist Question/Answer rows -> update Document.status
```

## Document processing approach
1. **Render**: PDFs are rendered page-by-page to PNG images (`pdf2image` /
   poppler). Images (jpg/png) are treated as single-page documents. This
   normalizes every input type into "a sequence of page images" before any
   extraction logic runs.
2. **Extract**: each page image is sent to a vision-capable LLM (Google Gemini) with
   a strict JSON-schema prompt (see `app/services/extraction_service.py`).
   The model performs OCR + layout understanding + structured extraction in
   one call. This is what lets the system handle scanned/rotated/blurry pages
   and varied numbering/option formats without hand-written regex parsers, at
   the cost of per-page API latency/cost.
3. **Stitch**: a question that is cut off at the bottom of a page is flagged
   `continues_on_next_page` by the model; the corresponding fragment on the
   next page is flagged `continues_from_previous_page`. A lightweight
   stitching pass (`stitch_multi_page_questions`) merges these into one
   question record with a `source_pages` list, so the API always exposes
   which page(s) a question came from.
4. **Answer-key association**: pages classified as `answer_key` (either in the
   same document, or in a sibling document in the same "document group") are
   parsed into `(question_number, answer_text)` pairs and matched to
   questions by *normalized* question number (case/format-insensitive exact
   match). Unmatched answers are left `is_matched=False` rather than guessed.
5. **Confidence & review**: every extracted question and every extracted
   answer carries a confidence score from the model. Questions below
   `CONFIDENCE_REVIEW_THRESHOLD` (default 0.6) are flagged `needs_review=True`
   with a reason, and are retrievable via a dedicated review-items endpoint.

## Storage design
- **Postgres**: `users`, `document_groups`, `documents`, `pages`, `questions`,
  `answers`. `pages.raw_ai_response` stores the full model output per page for
  auditability (a reviewer can trace any question back to the exact model
  response and page image).
- **File storage**: uploaded originals + rendered page images are written to
  a local `storage/` volume (mounted into both `api` and `worker` containers).
  This is the fastest path for a 24h/1-2h build; swapping in S3-compatible
  object storage is a drop-in change to `ocr_service.py` / the upload handler.

## Asynchronous processing
Upload returns immediately (`status=pending`); a Celery task
(`process_document_task`) does the actual rendering + extraction + persistence
work on a separate `worker` process, backed by Redis as broker/result store.
Clients poll `GET /documents/{id}/status` (or a webhook could be added).
Documents in the same group are matched for answers only after both are
`completed`, since a race is possible if they're uploaded back-to-back — see
worker.py TODO for a follow-up "resolve group answers" task.

## Question extraction strategy
Model-first (see above), rather than a hand-rolled Tesseract + regex pipeline,
per the assignment's explicit allowance for AI-based processing and its
statement that a perfect OCR system isn't expected. This trades per-page
inference cost for much better robustness to layout variation.

## Confidence / review mechanism
Two-tier: page-level (`Page.processed` bool + stored raw response, so a
totally failed page doesn't silently disappear) and question-level
(`extraction_confidence` float + `needs_review` bool + `review_reason`
string). A dedicated `GET /documents/{id}/review-items` endpoint surfaces the
review queue.

## Security considerations
- JWT auth (OAuth2 password flow); all document/question/answer endpoints are
  scoped to `owner_id` — no cross-user access.
- Upload validation: extension allow-list + max file size (env-configured).
- Secrets (DB creds, JWT secret, AI API key) are environment-based via `.env`,
  never committed (`.env.example` provided instead).
- AI API key is only ever used server-side inside the worker process, never
  exposed to the client.
- **Not yet implemented** (documented gap, see TODOs): virus/malware scanning
  of uploads, rate limiting, per-tenant storage isolation beyond DB row
  ownership, refresh tokens / token revocation.

## Scalability considerations
- Celery workers scale horizontally (more `worker` replicas) independent of
  the API process — page-level extraction is the bottleneck and is
  naturally parallelizable across documents and, with a small refactor,
  across pages within a document (currently sequential per document for
  simplicity).
- Redis as broker can be swapped for a managed queue (SQS, etc.) without
  touching business logic.
- Postgres is the single source of truth; read replicas would be the next
  scaling step for a read-heavy downstream consumer.

## Important trade-offs & limitations (honest list)
- No native-text extraction fast-path for digitally-generated PDFs — every
  page always goes through the vision model, which is simpler to build but
  not the cheapest/fastest option for text-heavy PDFs.
- Answer matching is exact-number-match only (no fuzzy/OCR-typo tolerance yet).
- Multi-page stitching is a greedy single-pending-question algorithm; a page
  with multiple simultaneously-continuing questions isn't handled.
- No malware/antivirus scanning on uploaded files.
- Local disk storage instead of object storage (fine for a take-home, not for
  production multi-instance deployment without a shared volume).
- IDs use `String(36)` rather than a native UUID column type (SQLite-testability
  trade-off, see README).

# Document Intelligence & Question Extraction Service

Upload PDFs/images of exam material and get back structured, machine-readable
questions (with options, type, source pages, confidence) and matched answer-key
entries, processed asynchronously.

## Stack
- **API**: FastAPI
- **DB**: PostgreSQL (SQLAlchemy 2.0 + Alembic migrations)
- **Async processing**: Celery + Redis
- **Extraction engine**: Google Gemini vision (per-page OCR + structured extraction in one call)
- **Auth**: JWT (OAuth2 password flow)

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY (and JWT_SECRET_KEY to something random)

docker compose up --build
```

This starts: `postgres`, `redis`, `api` (http://localhost:8000), `worker` (Celery).

Run migrations once containers are up:
```bash
docker compose exec api alembic revision --autogenerate -m "initial schema"
docker compose exec api alembic upgrade head
```

Swagger UI: http://localhost:8000/docs
OpenAPI JSON: http://localhost:8000/openapi.json

## Typical flow

1. `POST /auth/register` -> get a JWT
2. `POST /documents/upload` (multipart file) -> returns document id, status=pending
   - Processing kicks off automatically in the background (Celery task)
3. `GET /documents/{id}/status` -> poll until status is `completed` / `partially_completed` / `failed`
4. `GET /documents/{id}/questions` -> structured questions
5. `GET /documents/{id}/answers` -> matched answers
6. `GET /documents/{id}/review-items` -> low-confidence items needing human review

### Question paper + answer key as separate files
```
POST /documents/groups            {"name": "Midterm 2024"}
POST /documents/upload?group_id=<id>   (question paper)
POST /documents/upload?group_id=<id>   (answer key)
```
Once both finish processing, questions from the question-paper document will
have their answers matched from the answer-key document in the same group.

## Running tests
```bash
pip install -r requirements.txt
pytest app/tests -v
```
Tests use an isolated SQLite DB and mock the Celery task / AI call, so they
run without Docker, Postgres, Redis, or an API key.

## Environment variables
See `.env.example`. Never commit `.env`.

## Known trade-offs / what's intentionally minimal (see ARCHITECTURE.md)
- IDs are `String(36)` UUIDs rather than native Postgres UUID type, for
  SQLite-testability.
- No native-text fast path for digitally-generated PDFs yet — every page goes
  through the vision model, which is simpler but not the cheapest option.
- Answer matching is exact-number-match only, no fuzzy matching yet.

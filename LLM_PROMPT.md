# Prompt for VS Code Copilot (Agent/Edit mode)

Paste the block below into Copilot Chat with this whole project folder open
(ideally Copilot's **Agent mode** so it can read/edit multiple files, or at
minimum `@workspace` so it has file context). Do this in ONE pass, review the
diff, then run it — don't paste a giant new prompt for every file.

---

## PROMPT TO PASTE

You are working in an existing FastAPI + PostgreSQL + Redis/Celery project
called "Document Intelligence & Question Extraction Service". The full
architecture, models, routers, and service-layer scaffolding already exist —
your job is to **finish, fix, and harden it**, not redesign it. Read
`ARCHITECTURE.md` and `README.md` first for context.

### What already exists (don't rebuild these, just fix bugs if you find them):
- `app/models.py` — SQLAlchemy models: User, DocumentGroup, Document, Page, Question, Answer
- `app/schemas.py` — Pydantic request/response schemas
- `app/auth.py` + `app/routers/auth.py` — JWT register/login
- `app/routers/documents.py` — upload, list, status, document groups
- `app/routers/questions.py` — list/get questions, review items
- `app/routers/answers.py` — list/get answers
- `app/services/ocr_service.py` — renders PDF/image to page PNGs (pdf2image)
- `app/services/extraction_service.py` — calls Google Gemini vision API per page with
  a JSON-schema prompt, plus `stitch_multi_page_questions()` for questions
  spanning pages
- `app/services/answer_key_service.py` — normalizes + matches answer-key
  entries to questions by question number
- `app/tasks/worker.py` — the Celery task that orchestrates the whole
  render -> extract -> stitch -> match -> persist pipeline
- `app/tests/` — auth tests, document upload tests (mocked), extraction
  stitching tests, answer matching tests
- `docker-compose.yml`, `Dockerfile`, `alembic.ini` + `alembic/env.py`

### Your tasks, in priority order:

1. **Get it running.** `docker compose up --build`, generate the initial
   Alembic migration (`alembic revision --autogenerate -m "initial schema"`),
   apply it, hit `/health` and `/docs`. Fix any import errors, missing
   dependency versions, or Alembic config issues you hit. Tell me exactly
   what you had to fix and why — don't silently paper over errors.

2. **Validate the extraction prompt against a real file.** Take
   `sample_data/` (I will drop 2-3 real PDFs/images in there) and run the
   pipeline manually against one page (you can call
   `app.services.extraction_service.extract_page()` directly in a throwaway
   script) to sanity-check the JSON the model returns actually matches the
   schema and looks reasonable. Iterate on the prompt in
   `EXTRACTION_SYSTEM_PROMPT` if the output is malformed or low quality.
   **Do not tell me it works unless you've actually run it and seen real
  output** — if the GEMINI_API_KEY isn't set or you can't run it, say so
   explicitly instead of assuming success.

3. **Add the TODOs already flagged inline** (search the codebase for
   `TODO (Copilot)`), in this priority order if time-constrained:
   - `ocr_service.py`: native-text fast path for digital PDFs (skip vision
     call when a page already has selectable text via `pypdf`) — nice-to-have,
     skip if short on time.
   - `worker.py`: a `match_group_answers_task` that re-runs answer matching
     once both documents in a group are `completed` (handles the race where
     the question paper finishes processing before its answer-key sibling).
  - `extraction_service.py`: retry/backoff around the Gemini call; clamp
     confidence values to [0,1]; validate the JSON shape before trusting it
     (e.g. with a small Pydantic model) instead of trusting raw `json.loads`.
   - `answer_key_service.py`: fuzzy-match fallback for OCR-mangled numbers —
     only if there's time, keep it low priority/low confidence when it fires.

4. **Run the test suite** (`pytest app/tests -v`) and fix anything broken.
   Add 2-3 more tests if you spot an obviously untested code path (e.g. the
   `list_questions_for_document` `needs_review` filter, or a document-group
   answer-matching test in `worker.py` logic if you extract it into a
   testable function).

5. **Generate the Postman-run evidence and demo scenarios** listed in
   `postman_collection.json` and the assignment's "Demonstration
   Requirements" section (upload PDF, upload image, scanned/low-quality doc,
   multi-page question, options extraction, answer-key association,
   low-confidence extraction, final structured retrieval, invalid file
   rejection). Capture actual request/response screenshots or exported
   Postman run results — **do not fabricate example output**; if you can't
   actually exercise a scenario (e.g. no real low-quality scan on hand),
   tell me instead of inventing a plausible-looking result.

### Hard constraints — do not violate these:
- Don't remove the ownership checks in routers (`Document.owner_id ==
  current_user.id` etc.) — every endpoint must stay scoped to the
  authenticated user.
- Don't commit `.env` or hardcode the API key anywhere — it must only ever
  come from environment variables.
- Don't silently swallow exceptions in the worker pipeline — if a page or
  document fails, it should be reflected in `Document.status` /
  `Document.error_message`, not just logged and ignored.
- Keep the "unmatched answer stays unmatched" behavior — never have the
  matcher guess an answer it isn't confident about; that's an explicit
  requirement in the assignment brief.
- If you genuinely can't get something working in the time available, tell
  me clearly what's broken and why, rather than leaving it half-fixed with no
  explanation. I am responsible for validating and explaining this submission
  to the evaluators, so I need to actually understand what changed.

Work through tasks 1-4 now. Show me a summary of what you changed and why
after each task, not just a wall of diffs.

---

## After Copilot finishes

Manually double-check, yourself, before submitting:
- [ ] `docker compose up --build` actually starts all 4 containers cleanly
- [ ] You can register, login, upload a real PDF, and see it reach `completed`
- [ ] `/docs` (Swagger) loads and every endpoint listed in the assignment's
      "Required API Surface" is present
- [ ] You understand *why* the extraction prompt is structured the way it is
      — you'll likely be asked to explain it
- [ ] `.env` is NOT in your submitted zip/git history (check `git status`)
- [ ] Sample input + sample output JSON are actually included in your deliverable

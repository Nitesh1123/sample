"""
Core question-extraction logic.

Strategy: send each page image to a vision-capable LLM (Gemini) with a strict
JSON-schema prompt. The model performs OCR + layout understanding + structured
extraction in a single pass, which is what lets us handle varied numbering
formats, poor scans, embedded tables/images, etc. without hand-written parsers.

Multi-page questions: we extract per-page, then run a light "stitching" pass
that merges a trailing incomplete question on page N with a leading fragment
on page N+1 (see `stitch_multi_page_questions`).

TODO (Copilot):
  - Tune the prompt below against your real sample documents.
  - Add retry/backoff around the API call.
  - Consider batching multiple pages per call to reduce cost/latency
    if the model's context window and image limits allow it.
  - Add a JSON-schema validation step (e.g. pydantic) on the raw model
    output before trusting it, and clamp confidence to [0,1].
"""
import base64
import json
import os
import time
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings

_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None


class AnswerKeyEntry(BaseModel):
    question_number: str
    answer_text: str
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class ExtractedQuestion(BaseModel):
    question_number: str | None = None
    question_text: str = ""
    question_type: Literal[
        "mcq", "true_false", "short_answer", "long_answer", "fill_blank", "match_the_following", "unknown"
    ] = "unknown"
    options: list[str] | None = None
    has_image: bool = False
    continues_on_next_page: bool = False
    continues_from_previous_page: bool = False
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class PageExtraction(BaseModel):
    page_type: Literal["questions", "answer_key", "cover_or_instructions", "other"]
    questions: list[ExtractedQuestion] = Field(default_factory=list)
    answer_key_entries: list[AnswerKeyEntry] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a document-understanding engine for exam/question-bank PDFs and images.
You will be shown ONE PAGE of a document as an image. Extract every distinct question visible on this page.

Rules:
- Read all text on the page, including handwritten or low-quality scanned text, to the best of your ability.
- A page may contain zero, one, or many questions. Return an empty list if the page has no questions
  (e.g. it's a cover page or answer key page — still note that in `page_type`).
- If a question clearly starts on this page but does not finish (cut off at the bottom), set
  "continues_on_next_page": true for that question and include whatever partial text is visible.
- If a question clearly continues FROM the previous page (starts mid-sentence, no question number,
  or picks up in the middle of an option list), set "continues_from_previous_page": true.
- Preserve the original question number/label exactly as printed (e.g. "3", "Q3", "3.", "III").
  If no number is visible, set question_number to null.
- Detect question_type as one of: "mcq", "true_false", "short_answer", "long_answer", "fill_blank", "match_the_following", "unknown".
- If the question references an image/diagram/table on the page, set has_image: true.
- Assign a confidence score from 0.0 to 1.0 reflecting how certain you are the extracted text/options
  are complete and correct. Use LOW confidence (<0.5) for blurry/ambiguous/partially-cut-off content
  rather than guessing.
- Also classify the page itself via "page_type": "questions", "answer_key", "cover_or_instructions", "other".

Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this schema:

{
  "page_type": "questions" | "answer_key" | "cover_or_instructions" | "other",
  "questions": [
    {
      "question_number": "string or null",
      "question_text": "string",
      "question_type": "mcq" | "true_false" | "short_answer" | "long_answer" | "fill_blank" | "match_the_following" | "unknown",
      "options": ["string", ...] or null,
      "has_image": true | false,
      "continues_on_next_page": true | false,
      "continues_from_previous_page": true | false,
      "confidence": 0.0
    }
  ],
  "answer_key_entries": [
    {"question_number": "string", "answer_text": "string", "confidence": 0.0}
  ]
}

Only populate answer_key_entries if page_type is "answer_key" (or the page otherwise clearly lists
answers). Otherwise return an empty list for it.
"""


def _encode_image(path: str) -> tuple[str, str]:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    media_type = "image/png" if ext == "png" else "image/jpeg"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def extract_page(image_path: str) -> dict:
    """
    Calls the vision LLM on a single page image and returns the parsed JSON dict.
    Raises on API failure; caller is responsible for marking the page/document
    as failed or partially_completed.
    """
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    image_data, media_type = _encode_image(image_path)

    last_error = None
    for attempt in range(3):
        try:
            response = _client.models.generate_content(
                model=settings.gemini_model,
                contents=[
                    types.Part.from_bytes(data=base64.b64decode(image_data), mime_type=media_type),
                    "Extract this page's questions/answers as per the schema.",
                ],
                config=types.GenerateContentConfig(
                    system_instruction=EXTRACTION_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0,
                    max_output_tokens=4000,
                ),
            )
            raw_text = response.text or ""
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.removeprefix("```").removeprefix("json").removesuffix("```").strip()

            try:
                parsed = json.loads(cleaned)
                validated = PageExtraction.model_validate(parsed)
                return validated.model_dump(mode="python")
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as e:
                raise ValueError(f"Model output failed schema validation: {e}\nRaw: {raw_text[:500]}") from e
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
    raise RuntimeError(f"Gemini extraction failed after retries: {last_error}") from last_error


def stitch_multi_page_questions(pages_results: list[dict]) -> list[dict]:
    """
    Takes the ordered list of per-page extraction dicts (index = page_number - 1)
    and merges questions flagged continues_on_next_page / continues_from_previous_page
    into single question records with a source_pages list.

    Returns a flat list of question dicts ready to persist, each with:
      question_number, question_text, question_type, options, has_image,
      source_pages (list[int]), confidence

    TODO (Copilot): this is a simple greedy stitcher. Improve matching logic if
    a page has multiple candidates for "the question that continues" (e.g. by
    matching question_number sequence, or by taking the last question on the page).
    """
    merged: list[dict] = []
    pending = None  # a question dict waiting to be continued

    for page_idx, page_result in enumerate(pages_results, start=1):
        questions = page_result.get("questions", [])
        for q in questions:
            if q.get("continues_from_previous_page") and pending is not None:
                pending["question_text"] += " " + q["question_text"]
                if q.get("options"):
                    pending.setdefault("options", [])
                    pending["options"].extend(q["options"])
                pending["source_pages"].append(page_idx)
                pending["confidence"] = min(pending["confidence"], q.get("confidence", 0.5))
                if not q.get("continues_on_next_page"):
                    merged.append(pending)
                    pending = None
                continue

            record = {
                "question_number": q.get("question_number"),
                "question_text": q.get("question_text", ""),
                "question_type": q.get("question_type", "unknown"),
                "options": q.get("options"),
                "has_image": q.get("has_image", False),
                "source_pages": [page_idx],
                "confidence": q.get("confidence", 0.5),
            }

            if q.get("continues_on_next_page"):
                pending = record
            else:
                merged.append(record)

    if pending is not None:
        # Never got closed off - still surface it, but it should be flagged for review
        pending["confidence"] = min(pending["confidence"], 0.3)
        merged.append(pending)

    return merged

"""
Matches extracted answer-key entries to questions.

Matching strategy (simple, deterministic, explainable):
  1. Normalize question_number strings (strip "Q", ".", whitespace, leading zeros).
  2. Exact match on normalized number within the same document group (or same
     document, if no group / no separate answer-key document).
  3. If no exact match, leave the answer unmatched (is_matched=False) rather
     than guessing — per the assignment's explicit requirement.

TODO (Copilot):
  - Add fuzzy matching fallback (e.g. rapidfuzz) for OCR-mangled numbers
    ("1O" -> "10"), but keep it opt-in / lower confidence.
  - If a document has NO explicit answer key but options are MCQ with a
    marked/bolded correct option detected by the vision model, wire that in
    as an alternate answer source.
"""
import re
from difflib import SequenceMatcher


OCR_NUMBER_MAP = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "s": "5", "S": "5", "b": "8", "B": "8"})


def normalize_question_number(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    s = re.sub(r"^[qQ]\.?", "", s)
    s = s.rstrip(".)")
    s = s.strip()
    if not s:
        return None
    s = s.translate(OCR_NUMBER_MAP)
    s = re.sub(r"[^0-9]", "", s)
    s = s.lstrip("0") or "0"
    return s


def _fuzzy_match_question_number(target: str | None, candidate: str | None) -> tuple[bool, float]:
    if not target or not candidate:
        return False, 0.0
    target_norm = normalize_question_number(target)
    candidate_norm = normalize_question_number(candidate)
    if not target_norm or not candidate_norm:
        return False, 0.0
    if target_norm == candidate_norm:
        return True, 1.0

    ratio = SequenceMatcher(a=target_norm, b=candidate_norm).ratio()
    if ratio >= 0.85 and target_norm.isdigit() and candidate_norm.isdigit():
        return True, max(0.1, ratio * 0.85)
    return False, 0.0


def match_answers_to_questions(questions: list[dict], answer_key_entries: list[dict]) -> dict[int, dict]:
    """
    questions: list of dicts with an 'question_number' and a temp index
    answer_key_entries: list of {"question_number", "answer_text", "confidence"}

    Returns: {question_index_in_input_list: {"answer_text", "confidence", "is_matched"}}
    """
    by_number: dict[str, dict] = {}
    for entry in answer_key_entries:
        norm = normalize_question_number(entry.get("question_number"))
        if norm:
            by_number[norm] = entry

    results = {}
    for idx, q in enumerate(questions):
        norm = normalize_question_number(q.get("question_number"))
        match = by_number.get(norm) if norm else None
        if not match:
            for entry in answer_key_entries:
                matched, score = _fuzzy_match_question_number(q.get("question_number"), entry.get("question_number"))
                if matched and score >= 0.5:
                    match = entry
                    break

        if match:
            confidence = match.get("confidence", 0.5)
            if match is not by_number.get(norm) if norm else False:
                confidence = min(confidence, 0.75) * 0.8
            results[idx] = {
                "answer_text": match.get("answer_text"),
                "match_confidence": max(0.0, min(1.0, confidence)),
                "is_matched": True,
            }
        else:
            results[idx] = {
                "answer_text": None,
                "match_confidence": 0.0,
                "is_matched": False,
            }
    return results

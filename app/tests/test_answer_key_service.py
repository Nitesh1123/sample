from app.services.answer_key_service import normalize_question_number, match_answers_to_questions


def test_normalize_question_number_variants():
    assert normalize_question_number("Q3") == "3"
    assert normalize_question_number("3.") == "3"
    assert normalize_question_number("03") == "3"
    assert normalize_question_number(None) is None


def test_match_answers_exact():
    questions = [{"question_number": "1"}, {"question_number": "2"}, {"question_number": "3"}]
    answer_key = [
        {"question_number": "1", "answer_text": "A", "confidence": 0.9},
        {"question_number": "3", "answer_text": "C", "confidence": 0.8},
    ]
    result = match_answers_to_questions(questions, answer_key)

    assert result[0]["is_matched"] is True
    assert result[0]["answer_text"] == "A"
    assert result[1]["is_matched"] is False
    assert result[2]["is_matched"] is True
    assert result[2]["answer_text"] == "C"


def test_no_answer_key_leaves_all_unmatched():
    questions = [{"question_number": "1"}]
    result = match_answers_to_questions(questions, [])
    assert result[0]["is_matched"] is False
    assert result[0]["answer_text"] is None


def test_match_answers_with_ocr_mangled_number():
    questions = [{"question_number": "10"}]
    answer_key = [{"question_number": "1O", "answer_text": "B", "confidence": 0.68}]
    result = match_answers_to_questions(questions, answer_key)

    assert result[0]["is_matched"] is True
    assert result[0]["answer_text"] == "B"
    assert result[0]["match_confidence"] == 0.68

from app.services.extraction_service import stitch_multi_page_questions


def test_single_page_question_no_stitching_needed():
    pages = [
        {
            "page_type": "questions",
            "questions": [
                {"question_number": "1", "question_text": "What is 2+2?", "confidence": 0.95,
                 "continues_on_next_page": False, "continues_from_previous_page": False}
            ],
            "answer_key_entries": [],
        }
    ]
    result = stitch_multi_page_questions(pages)
    assert len(result) == 1
    assert result[0]["source_pages"] == [1]
    assert result[0]["question_text"] == "What is 2+2?"


def test_question_spanning_two_pages_is_merged():
    pages = [
        {
            "page_type": "questions",
            "questions": [
                {"question_number": "5", "question_text": "Explain the water cycle in detail,",
                 "confidence": 0.7, "continues_on_next_page": True, "continues_from_previous_page": False}
            ],
            "answer_key_entries": [],
        },
        {
            "page_type": "questions",
            "questions": [
                {"question_number": None, "question_text": "including evaporation and condensation.",
                 "confidence": 0.6, "continues_on_next_page": False, "continues_from_previous_page": True}
            ],
            "answer_key_entries": [],
        },
    ]
    result = stitch_multi_page_questions(pages)
    assert len(result) == 1
    assert result[0]["source_pages"] == [1, 2]
    assert "evaporation" in result[0]["question_text"]
    assert result[0]["confidence"] == 0.6  # min of the two


def test_unclosed_continuation_still_surfaces_with_low_confidence():
    pages = [
        {
            "page_type": "questions",
            "questions": [
                {"question_number": "9", "question_text": "Describe...", "confidence": 0.8,
                 "continues_on_next_page": True, "continues_from_previous_page": False}
            ],
            "answer_key_entries": [],
        }
    ]
    result = stitch_multi_page_questions(pages)
    assert len(result) == 1
    assert result[0]["confidence"] <= 0.3

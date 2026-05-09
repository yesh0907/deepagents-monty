from __future__ import annotations

from types import SimpleNamespace

from evals.data_analysis.run import extract_answer_content, grade_answer


def test_extract_answer_content_returns_plain_string() -> None:
    assert extract_answer_content("336773.84") == "336773.84"


def test_extract_answer_content_prefers_final_answer_block() -> None:
    content = [
        {"type": "text", "text": "working..."},
        {"type": "text", "text": "336773.84", "phase": "final_answer"},
    ]

    assert extract_answer_content(content) == "336773.84"


def test_extract_answer_content_reads_responses_text_block() -> None:
    content = [{"type": "output_text", "text": "Savings Transfer"}]

    assert extract_answer_content(content) == "Savings Transfer"


def test_extract_answer_content_reads_object_text_block() -> None:
    content = [SimpleNamespace(text="120.47", phase="final_answer")]

    assert extract_answer_content(content) == "120.47"


def test_structured_final_answer_grades_against_scalar_expected() -> None:
    content = [
        {
            "type": "text",
            "text": "336773.84",
            "annotations": [],
            "id": "msg_123",
            "phase": "final_answer",
        }
    ]

    actual = extract_answer_content(content)

    assert actual == "336773.84"
    assert grade_answer(actual, "336773.84", 0.0)

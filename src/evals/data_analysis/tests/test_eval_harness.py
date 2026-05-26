from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import evals.data_analysis.run as run_module
from evals.data_analysis.run import (
    extract_answer_content,
    grade_answer,
    make_model,
    parse_args,
    parse_model_id,
    reasoning_effort_kwargs,
    selected_agents,
)


def test_parse_model_id_reads_provider_prefix() -> None:
    assert parse_model_id("openai:gpt-5.5") == ("openai", "gpt-5.5")
    assert parse_model_id("anthropic:claude-sonnet-4-6") == (
        "anthropic",
        "claude-sonnet-4-6",
    )


def test_parse_model_id_allows_unprefixed_model() -> None:
    assert parse_model_id("gpt-5.5") == (None, "gpt-5.5")


@pytest.mark.parametrize("model", ["openai:", ":gpt-5.5"])
def test_parse_model_id_rejects_empty_provider_or_model(model: str) -> None:
    with pytest.raises(ValueError, match="provider:model-name"):
        parse_model_id(model)


def test_parse_args_accepts_reasoning_effort() -> None:
    args = parse_args(["--model", "openai:gpt-5.5", "--reasoning-effort", "medium"])

    assert args.model == "openai:gpt-5.5"
    assert args.reasoning_effort == "medium"


def test_parse_args_defaults_to_mini_model_low_reasoning_and_all_variants() -> None:
    args = parse_args([])

    assert args.model == "openai:gpt-5.4-mini"
    assert args.reasoning_effort == "low"
    assert args.variant == "all"


def test_parse_args_does_not_default_reasoning_when_model_is_provided() -> None:
    args = parse_args(["--model", "anthropic:claude-sonnet-4-6"])

    assert args.model == "anthropic:claude-sonnet-4-6"
    assert args.reasoning_effort is None


def test_parse_args_accepts_single_variant() -> None:
    args = parse_args(["--variant", "monty"])

    assert args.variant == "monty"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", {"reasoning_effort": "low"}),
        ("google_genai", {"thinking_level": "low"}),
        ("google_vertexai", {"thinking_level": "low"}),
        ("anthropic", {"effort": "low"}),
        (None, {"reasoning_effort": "low"}),
    ],
)
def test_reasoning_effort_kwargs_uses_provider_specific_name(
    provider: str | None,
    expected: dict[str, str],
) -> None:
    assert reasoning_effort_kwargs(provider, "low") == expected


def test_make_model_forwards_provider_specific_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_init_chat_model(
        model: str,
        *,
        model_provider: str | None = None,
        **kwargs: Any,
    ) -> object:
        captured.update(
            {
                "model": model,
                "model_provider": model_provider,
                "kwargs": kwargs,
            }
        )
        return object()

    monkeypatch.setattr(run_module, "init_chat_model", fake_init_chat_model)

    make_model(model="google_genai:gemini-2.5-pro", reasoning_effort="medium")

    assert captured == {
        "model": "gemini-2.5-pro",
        "model_provider": "google_genai",
        "kwargs": {"name": "agent", "thinking_level": "medium"},
    }


def test_selected_agents_constructs_only_requested_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_models: list[str] = []
    constructed_agents: list[bool] = []

    def fake_make_model(**kwargs: Any) -> object:
        constructed_models.append(kwargs["name"])
        return object()

    def fake_make_agent(**kwargs: Any) -> object:
        constructed_agents.append(kwargs["with_monty"])
        return object()

    monkeypatch.setattr(run_module, "make_model", fake_make_model)
    monkeypatch.setattr(run_module, "make_agent", fake_make_agent)

    agents = selected_agents(
        variant="monty",
        model_name="openai:gpt-5.4-mini",
        base_url=None,
        reasoning_effort="low",
    )

    assert list(agents) == ["monty"]
    assert constructed_models == ["monty-agent"]
    assert constructed_agents == [True]


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

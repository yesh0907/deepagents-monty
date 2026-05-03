"""Middleware-surface tests: tool registration, schema, system prompt, defaults."""

from __future__ import annotations

from typing import Any, cast

import pytest
from deepagents.backends import StateBackend
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from deepagents_monty import MontyCodeMiddleware


class _FakeRequest:
    """Minimal stand-in for ModelRequest in unit-level wrap_model_call tests."""

    def __init__(self, system_message: SystemMessage | None):
        self.system_message = system_message

    def override(self, *, system_message: SystemMessage) -> _FakeRequest:
        self.system_message = system_message
        return self


def _combine_text(sm: SystemMessage) -> str:
    return " ".join(b.get("text", "") for b in sm.content_blocks if b.get("type") == "text")


def test_registers_execute_python_tool():
    mw = MontyCodeMiddleware(backend=StateBackend())
    assert [t.name for t in mw.tools] == ["execute_python"]


def test_tool_schema_hides_runtime():
    """The `runtime` parameter is injected; it must not appear in the JSON schema."""
    mw = MontyCodeMiddleware(backend=StateBackend())
    schema = convert_to_openai_tool(mw.tools[0])
    props = schema["function"]["parameters"]["properties"]
    assert set(props.keys()) == {"code"}


def test_system_prompt_appended_preserves_original():
    mw = MontyCodeMiddleware(backend=StateBackend())
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)

    text = _combine_text(captured["system"])
    assert "You are helpful." in text, "original system prompt dropped"
    for phrase in (
        "execute_python",
        "pathlib.Path",
        "read_file",
        "third-party libraries",
    ):
        assert phrase in text, f"system prompt missing: {phrase!r}"


def test_backend_is_required():
    """Matches SkillsMiddleware / MemoryMiddleware pattern - no silent default."""
    with pytest.raises(TypeError, match="backend"):
        MontyCodeMiddleware()  # type: ignore[call-arg]


async def test_type_check_enabled_by_default_catches_bad_types():
    mw = MontyCodeMiddleware(backend=StateBackend())
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None
    result = await tool.coroutine(code='x: int = "not an int"\nx', runtime=None)
    assert result.startswith("TypeError:")


async def test_type_check_can_be_disabled():
    mw = MontyCodeMiddleware(backend=StateBackend(), type_check=False)
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None
    result = await tool.coroutine(code='x: int = "not an int"\nx', runtime=None)
    assert "return:" in result, f"expected the expression to evaluate, got: {result}"

"""Middleware-surface tests: tool registration, schema, system prompt, defaults."""

from __future__ import annotations

import contextvars
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, cast

import pytest
from deepagents.backends import StateBackend
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from deepagents_monty import MONTY_SYSTEM_PROMPT, MontyCodeMiddleware


class _FakeRequest:
    """Minimal stand-in for ModelRequest in unit-level wrap_model_call tests."""

    def __init__(self, system_message: SystemMessage | None):
        self.system_message = system_message

    def override(self, *, system_message: SystemMessage) -> _FakeRequest:
        self.system_message = system_message
        return self


def _combine_text(sm: SystemMessage) -> str:
    return " ".join(b.get("text", "") for b in sm.content_blocks if b.get("type") == "text")


def test_registers_python_repl_tool():
    mw = MontyCodeMiddleware(backend=StateBackend())
    assert [t.name for t in mw.tools] == ["python_repl"]


def test_tool_schema_hides_runtime():
    """The `runtime` parameter is injected; it must not appear in the JSON schema."""
    mw = MontyCodeMiddleware(backend=StateBackend())
    schema = convert_to_openai_tool(mw.tools[0])
    props = schema["function"]["parameters"]["properties"]
    assert set(props.keys()) == {"code", "restart"}
    assert "reset REPL state" in props["restart"]["description"]


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
        "python_repl",
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


async def test_python_repl_rejects_parallel_tool_call_batch():
    mw = MontyCodeMiddleware(backend=StateBackend())
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None
    runtime = SimpleNamespace(
        state={
            "messages": [
                SimpleNamespace(
                    tool_calls=[
                        {"name": "python_repl", "args": {"code": "1 + 1"}, "id": "a"},
                        {"name": "read_file", "args": {"file_path": "/x"}, "id": "b"},
                    ]
                )
            ]
        }
    )

    result = await tool.coroutine(code="1 + 1", runtime=runtime)

    assert result.startswith("RuntimeError: python_repl cannot run in parallel")


async def test_external_sync_function_available_to_monty():
    def double(value: int) -> int:
        return value * 2

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"double": double},
        type_check_stubs="def double(value: int) -> int: ...",
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code="double(21)", runtime=None)

    assert result == "return: 42"


async def test_external_async_function_available_to_monty_with_await():
    async def fetch_value(value: int) -> int:
        return value + 1

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"fetch_value": fetch_value},
        type_check_stubs="async def fetch_value(value: int) -> int: ...",
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code="await fetch_value(41)", runtime=None)

    assert result == "return: 42"


async def test_external_async_function_runs_in_captured_context():
    value_var = contextvars.ContextVar("value", default="missing")

    async def read_context() -> str:
        return value_var.get()

    token = value_var.set("captured")
    try:
        mw = MontyCodeMiddleware(
            backend=StateBackend(),
            external_functions={"read_context": read_context},
            type_check_stubs="async def read_context() -> str: ...",
        )
        tool = cast(StructuredTool, mw.tools[0])
        assert tool.coroutine is not None

        result = await tool.coroutine(code="await read_context()", runtime=None)
    finally:
        value_var.reset(token)

    assert result == "return: 'captured'"


async def test_type_check_stubs_describe_external_functions():
    def typed_add(left: int, right: int) -> int:
        return left + right

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"typed_add": typed_add},
        type_check_stubs="def typed_add(left: int, right: int) -> int: ...",
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code='typed_add("x", 1)', runtime=None)

    assert result.startswith("TypeError:")


async def test_external_function_signatures_are_auto_stubbed_for_type_checking():
    def typed_add(left: int, right: int) -> int:
        return left + right

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"typed_add": typed_add},
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code='typed_add("x", 1)', runtime=None)

    assert result.startswith("TypeError:")


async def test_external_function_auto_stubs_handle_non_builtin_annotations():
    def path_name(path: Path) -> str:
        return str(path)

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"path_name": path_name},
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code="path_name('/tmp/example')", runtime=None)

    assert "SyntaxError" not in result
    assert "MontyError" not in result


def test_external_function_stubs_are_appended_to_system_prompt():
    stubs = "async def fetch_value(value: int) -> int: ..."
    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"fetch_value": lambda value: value},
        type_check_stubs=stubs,
    )
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)

    text = _combine_text(captured["system"])
    assert stubs in text
    assert "Call async functions with `await`" in text


def test_external_function_signatures_are_auto_appended_to_system_prompt():
    async def fetch_value(value: int) -> int:
        return value + 1

    def double(value: int) -> int:
        return value * 2

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"fetch_value": fetch_value, "double": double},
    )
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)

    text = _combine_text(captured["system"])
    assert "do not redefine or import them" in text
    assert "Async functions (`async def`) must be called with `await`" in text
    assert "Sync functions (`def`) are called normally" in text
    assert "async def fetch_value(value: int) -> int: ..." in text
    assert "def double(value: int) -> int: ..." in text


def test_external_function_auto_stubs_import_annotation_modules():
    def maybe_path(path: Path | None, fallback: Optional[Path] = None) -> Path:  # noqa: UP045
        return path or fallback or Path("/")

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"maybe_path": maybe_path},
    )
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)

    text = _combine_text(captured["system"])
    assert "from typing import" in text
    assert "Optional" in text
    assert "import pathlib" in text
    assert "pathlib.Path" in text
    assert "<class 'pathlib.Path'>" not in text


def test_external_function_prompt_tailors_async_only_guidance():
    async def fetch_value(value: int) -> int:
        return value + 1

    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"fetch_value": fetch_value},
    )
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)

    text = _combine_text(captured["system"])
    assert "All external functions are async" in text
    assert "Calling without `await` returns an unresolved future" in text


def _capture_injected_prompt(mw: MontyCodeMiddleware) -> str:
    """Run wrap_model_call and return the injected system prompt text."""
    captured: dict = {}

    def handler(req):
        captured["system"] = req.system_message
        return "ok"

    req = _FakeRequest(SystemMessage(content="You are helpful."))
    mw.wrap_model_call(cast(ModelRequest[Any], req), handler)
    return _combine_text(captured["system"])


def test_monty_system_prompt_is_importable_and_matches_default():
    """The default prompt is publicly exposed and equals the injected default."""
    assert isinstance(MONTY_SYSTEM_PROMPT, str)
    assert "python_repl" in MONTY_SYSTEM_PROMPT
    assert "third-party libraries" in MONTY_SYSTEM_PROMPT

    mw = MontyCodeMiddleware(backend=StateBackend())
    text = _capture_injected_prompt(mw)
    # With no external functions, the injected prompt is exactly the default base.
    assert MONTY_SYSTEM_PROMPT in text


def test_append_system_prompt_appends_to_default():
    extra = "When a task involves loops or JSON parsing, reach for python_repl."
    mw = MontyCodeMiddleware(backend=StateBackend(), append_system_prompt=extra)

    text = _capture_injected_prompt(mw)

    # Default mechanics text is still present...
    for phrase in ("python_repl", "pathlib.Path", "read_file", "third-party libraries"):
        assert phrase in text, f"default prompt missing: {phrase!r}"
    # ...and the appended guidance is present too.
    assert extra in text


def test_append_system_prompt_composes_with_custom_system_prompt():
    custom_base = "CUSTOM BASE PROMPT describing the sandbox."
    extra = "EXTRA GUIDANCE about when to use it."
    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        system_prompt=custom_base,
        append_system_prompt=extra,
    )

    text = _capture_injected_prompt(mw)

    assert custom_base in text
    assert extra in text
    # The default mechanics doc is replaced by the custom base, so its
    # distinctive text should be absent.
    assert "third-party libraries (pandas, requests, numpy, etc.)" not in text


def test_append_system_prompt_keeps_external_function_stubs():
    """append_system_prompt must not break the type-stub path: stubs still append."""
    stubs = "def typed_add(left: int, right: int) -> int: ..."
    extra = "Prefer python_repl for arithmetic over many tool calls."
    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"typed_add": lambda left, right: left + right},
        type_check_stubs=stubs,
        append_system_prompt=extra,
    )

    text = _capture_injected_prompt(mw)

    # Default base, appended guidance, and the external-function stubs are all present.
    assert "third-party libraries" in text
    assert extra in text
    assert stubs in text
    assert "do not redefine or import them" in text


async def test_external_functions_do_not_override_builtins():
    mw = MontyCodeMiddleware(
        backend=StateBackend(),
        external_functions={"len": lambda value: 99},
        type_check=False,
    )
    tool = cast(StructuredTool, mw.tools[0])
    assert tool.coroutine is not None

    result = await tool.coroutine(code="len([1, 2, 3])", runtime=None)

    assert result == "return: 3"

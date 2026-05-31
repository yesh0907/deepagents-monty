"""MontyCodeMiddleware: a Deep Agents middleware that adds a Monty-backed
``python_repl`` tool sharing the agent's filesystem.

See README.md for the design discussion. The short version:

- ``backend`` is required (matches SkillsMiddleware / MemoryMiddleware; this
  is a consumer of shared filesystem, not a provider).
- ``type_check=True`` by default (catches type errors at parse-time for ~15-30ms).
- The filesystem bridge uses the sync backend contract; optional
  ``external_functions`` can expose sync or async host callables.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import inspect
from collections.abc import Callable
from types import UnionType
from typing import Annotated, Any

import pydantic_monty as pm
from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain.agents.middleware.types import OmitFromSchema
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command
from pydantic import Field
from pydantic_monty import MontyRepl, ResourceLimits
from typing_extensions import TypedDict

from .bridge import DeepAgentBackendOS

__all__ = [
    "MONTY_SYSTEM_PROMPT",
    "MontyCodeMiddleware",
    "build_system_prompt",
    "make_execute_python",
]

_REPL_STATE_KEY = "monty_repl_state_b64"


class MontyCodeState(TypedDict, total=False):
    monty_repl_state_b64: Annotated[str, OmitFromSchema()]


EXECUTE_PYTHON_DESCRIPTION = """\
Write and run Python code in a secure Monty-backed REPL sandbox.

Files: read/write via pathlib.Path. Paths must be absolute (start with /).
These files are the SAME ones ls/read_file/write_file/edit_file see.

State is preserved between calls (REPL-style). Set restart=true to reset
the REPL state before running the snippet.

Limitations:
- Subset of Python only: no classes, no match statements, no generators,
  no context managers (yet).
- No third-party libraries (pandas, requests, etc.).
- Importable standard library modules: sys, typing, asyncio, math, json, re,
  datetime, os, pathlib. Import them at the top of your snippet before use.
- No wall-clock or timing primitives: asyncio.sleep, datetime.datetime.now(),
  datetime.date.today(), and the time module are unavailable.
- No import * wildcard imports.
- Do not call in parallel with other tools. Run one python_repl call at a time.
- Files cannot be deleted or renamed - overwrite with empty content instead.
- Directories are implicit (they exist only when they contain files).

The last expression's value is captured as the return value. Do not print()
return values; use print() only for supplementary logging or debugging.
"""


_MONTY_SYSTEM_PROMPT = """\
## Code execution (`python_repl`)

You have access to `python_repl` for writing and running Python code in a \
secure Monty-backed REPL sandbox. This is the right tool when a task is easier to \
express as code than as a sequence of filesystem tool calls - loops, \
conditionals, data transforms, JSON parsing, etc.

State is preserved between calls (REPL-style). Set `restart=true` to reset \
the REPL state before running a snippet.

Filesystem sharing: code run via `python_repl` reads and writes files \
through `pathlib.Path`, and sees the SAME filesystem as `ls`, `read_file`, \
`write_file`, `edit_file`, `glob`, and `grep`. Paths must be absolute \
(start with `/`).

Limitations to be aware of:
- This is a Python subset: no class definitions, no match statements, no \
context managers (yet).
- No third-party libraries (pandas, requests, numpy, etc.). Only core \
syntax and a small stdlib subset (`sys`, `typing`, `asyncio`, `math`, \
`json`, `re`, `datetime`, `os`, `pathlib`). Import modules at the top of \
your snippet before use.
- No wall-clock or timing primitives: `asyncio.sleep`, \
`datetime.datetime.now()`, `datetime.date.today()`, and the `time` module \
are unavailable.
- No `import *` wildcard imports.
- Files cannot be deleted or renamed. To "delete", overwrite with empty \
content. Directories are implicit - they exist only when they contain files.
- Do not call `python_repl` in parallel with other tools. It is an ordered \
REPL-style execution surface, so run one snippet at a time and wait for the \
tool result before deciding the next tool call.
- The last top-level expression is captured as the return value. Do not \
`print()` return values; use `print()` only for supplementary logging or \
debugging.
"""

# Public alias for the default system prompt. Advanced consumers can import this
# to introspect or compose against the default prompt without reaching for the
# private ``_MONTY_SYSTEM_PROMPT`` symbol. The private name is retained for
# backward compatibility.
MONTY_SYSTEM_PROMPT = _MONTY_SYSTEM_PROMPT


def _append_to_system_message(system_message: SystemMessage | None, text: str) -> SystemMessage:
    """Append text to a system message, preserving any prior content.

    Inlined from ``deepagents.middleware._utils`` (private module) so this
    package doesn't break if deepagents refactors. Original logic credit:
    LangChain / Deep Agents.
    """
    new_content = list(system_message.content_blocks) if system_message else []
    if new_content:
        text = f"\n\n{text}"
    new_content.append({"type": "text", "text": text})
    return SystemMessage(content_blocks=new_content)


def build_system_prompt(
    *,
    system_prompt: str | None = None,
    append: str | None = None,
) -> str:
    """Compose the base ``python_repl`` system prompt.

    The base is ``system_prompt`` if provided, otherwise the default
    :data:`MONTY_SYSTEM_PROMPT`. If ``append`` is provided, it is added after
    the base separated by a blank line. ``system_prompt`` and ``append`` compose
    independently: you can replace the base, append to the default, both, or
    neither.

    This returns only the human-authored base prompt. ``MontyCodeMiddleware``
    additionally appends any ``external_functions`` type stubs after this base
    when building the prompt it injects into the model request.
    """
    base = system_prompt if system_prompt is not None else MONTY_SYSTEM_PROMPT
    if append:
        return f"{base}\n\n{append}"
    return base


def make_execute_python(
    *,
    backend: BackendProtocol,
    external_functions: dict[str, Callable[..., Any]] | None = None,
    type_check_stubs: str | None = None,
    max_duration_secs: float = 10.0,
    type_check: bool = True,
) -> StructuredTool:
    """Build a standalone ``python_repl`` tool.

    Most users should prefer :class:`MontyCodeMiddleware`, which also handles
    system-prompt injection. This helper is for advanced setups that want to
    register the tool manually (e.g. alongside custom middleware composition).
    """
    effective_type_check_stubs = _resolve_type_check_stubs(
        external_functions=external_functions,
        type_check_stubs=type_check_stubs,
    )

    async def execute_python(
        code: Annotated[str, Field(description="The Python code to execute in the sandbox.")],
        runtime: ToolRuntime,
        restart: Annotated[
            bool,
            Field(
                description=(
                    "Set to true to reset REPL state before running this snippet. "
                    "When false (default), state is preserved between calls."
                )
            ),
        ] = False,
    ) -> str | Command:
        if parallel_error := _parallel_tool_call_error(runtime):
            return parallel_error

        fs = DeepAgentBackendOS(backend)
        wrapped_external_functions = _wrap_external_functions_in_context(external_functions)
        stdout_chunks: list[str] = []

        def capture_print(stream: str, text: str) -> None:
            stdout_chunks.append(text)

        try:
            repl = _load_repl(
                runtime,
                limits=ResourceLimits(max_duration_secs=max_duration_secs),
                type_check=type_check,
                type_check_stubs=effective_type_check_stubs,
                restart=restart,
            )
        except pm.MontySyntaxError as e:
            return f"SyntaxError: {e}"
        except pm.MontyTypingError as e:
            return f"TypeError: {e}"
        except (ValueError, TypeError) as e:
            return f"MontyError: {type(e).__name__}: {e}"

        try:
            result = await repl.feed_run_async(
                code,
                os=fs,
                external_functions=wrapped_external_functions,
                print_callback=capture_print,
            )
            content = _format_result(result, stdout_chunks)
        except pm.MontyRuntimeError as e:
            stdout = "".join(stdout_chunks)
            tail = f"\n--stdout--\n{stdout}" if stdout else ""
            content = f"RuntimeError: {e}{tail}"
        except pm.MontySyntaxError as e:
            content = f"SyntaxError: {e}"
        except pm.MontyTypingError as e:
            content = f"TypeError: {e}"
        except pm.MontyError as e:
            content = f"MontyError: {type(e).__name__}: {e}"

        return _tool_result(content, repl, runtime)

    return StructuredTool.from_function(
        coroutine=execute_python,
        name="python_repl",
        description=EXECUTE_PYTHON_DESCRIPTION,
    )


def _load_repl(
    runtime: ToolRuntime | None,
    *,
    limits: ResourceLimits,
    type_check: bool,
    type_check_stubs: str | None,
    restart: bool,
) -> MontyRepl:
    state_b64 = None if restart else _get_repl_state_b64(runtime)
    if state_b64 is not None:
        return MontyRepl.load(base64.b64decode(state_b64.encode("ascii")))

    return MontyRepl(limits=limits, type_check=type_check, type_check_stubs=type_check_stubs)


def _get_repl_state_b64(runtime: ToolRuntime | None) -> str | None:
    state = getattr(runtime, "state", None)
    if not isinstance(state, dict):
        return None
    value = state.get(_REPL_STATE_KEY)
    return value if isinstance(value, str) and value else None


def _format_result(result: Any, stdout_chunks: list[str]) -> str:
    stdout = "".join(stdout_chunks)
    parts = [f"return: {result!r}"]
    if stdout:
        parts.append(f"--stdout--\n{stdout}")
    return "\n".join(parts)


def _tool_result(content: str, repl: MontyRepl, runtime: ToolRuntime | None) -> str | Command:
    tool_call_id = getattr(runtime, "tool_call_id", None)
    if not tool_call_id:
        return content

    state_b64 = base64.b64encode(repl.dump()).decode("ascii")
    return Command(
        update={
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
            _REPL_STATE_KEY: state_b64,
        }
    )


def _parallel_tool_call_error(runtime: ToolRuntime | None) -> str | None:
    """Return a model-visible error if ``python_repl`` is in a parallel batch."""
    if runtime is None:
        return None

    state = getattr(runtime, "state", None)
    if not isinstance(state, dict):
        return None

    messages = state.get("messages")
    if not messages:
        return None

    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if not tool_calls and isinstance(last_message, dict):
        tool_calls = last_message.get("tool_calls")
    if not tool_calls or len(tool_calls) <= 1:
        return None

    return (
        "RuntimeError: python_repl cannot run in parallel with other tool calls. "
        "Call python_repl by itself, wait for the result, then make any follow-up tool calls."
    )


class MontyCodeMiddleware(AgentMiddleware):
    state_schema: type[Any] = MontyCodeState

    """Adds a ``python_repl`` tool backed by the Monty interpreter.

    Code executed via this tool shares the filesystem with any other
    BackendProtocol-using middleware (e.g. ``FilesystemMiddleware``): a file
    written through ``python_repl`` is readable via ``read_file``, and
    vice versa, as long as both middlewares use the same backend instance.

    Typical usage::

        from deepagents import create_deep_agent
        from deepagents.backends import StateBackend
        from deepagents_monty import MontyCodeMiddleware

        backend = StateBackend()
        agent = create_deep_agent(
            model=...,
            backend=backend,                    # used by FilesystemMiddleware
            middleware=[MontyCodeMiddleware(backend=backend)],
        )
    """

    def __init__(
        self,
        *,
        backend: BackendProtocol,
        system_prompt: str | None = None,
        append_system_prompt: str | None = None,
        external_functions: dict[str, Callable[..., Any]] | None = None,
        type_check_stubs: str | None = None,
        max_duration_secs: float = 10.0,
        type_check: bool = True,
    ):
        """Initialize the middleware.

        Args:
            backend: BackendProtocol to share with the rest of the agent.
                Required - pass the same instance you pass to
                ``create_deep_agent(backend=...)`` so code executed via
                ``python_repl`` sees the same files as ``read_file``,
                ``write_file``, etc. We follow the pattern of
                ``SkillsMiddleware`` and ``MemoryMiddleware`` (required
                backend), rather than ``FilesystemMiddleware`` (defaults to
                ``StateBackend()``), because ``MontyCodeMiddleware`` is a
                *consumer* of the shared filesystem - silently defaulting
                to a new backend would create two disjoint filesystems
                and break cross-tool file sharing without warning.
            system_prompt: Override for the default Monty system prompt
                that describes ``python_repl`` to the model. When provided, it
                *replaces* the default :data:`MONTY_SYSTEM_PROMPT` (you lose the
                built-in mechanics/limitations doc). Use ``append_system_prompt``
                instead when you only want to add guidance on top of the default.
            append_system_prompt: Optional extra guidance appended after the
                base prompt (separated by a blank line). The base is
                ``system_prompt`` if provided, else the default
                :data:`MONTY_SYSTEM_PROMPT`. ``system_prompt`` and
                ``append_system_prompt`` compose independently: append to the
                default (the common case - e.g. "when to reach for
                ``python_repl``" guidance), replace the base entirely, or do
                both. Any ``external_functions`` type stubs are still appended
                *after* this composed base, exactly as without
                ``append_system_prompt``.
            external_functions: Optional host functions exposed to Monty code
                as unresolved global names. These do not override Monty
                builtins, imports, or names defined by the executed code.
                Both sync functions and async coroutine functions are
                supported by Monty's ``run_async`` runtime. Async functions
                must be called with ``await`` in sandbox code.
            type_check_stubs: Optional Python stub text describing any
                external functions/types. This text is passed to Monty's type
                checker and appended to the system prompt so the model knows
                the available call signatures. Prefer JSON-like return values
                (``str``, ``int``, ``float``, ``bool``, ``None``, ``list``,
                ``dict``) for the most stable model-facing API; richer values
                may work when supported by Monty and accurately described here.
            max_duration_secs: Per-call wallclock cap for sandboxed code.
            type_check: Whether Monty should run its built-in static type
                checker (using ``ty``) at parse time. Adds 15-30ms at
                parse, zero at runtime, and gives the model a clear
                diagnostic before its code starts executing. Defaults to
                True to match Pydantic AI's code-mode default.
        """
        super().__init__()
        self._backend = backend
        base_prompt = build_system_prompt(
            system_prompt=system_prompt,
            append=append_system_prompt,
        )
        effective_type_check_stubs = _resolve_type_check_stubs(
            external_functions=external_functions,
            type_check_stubs=type_check_stubs,
        )
        self._system_prompt = _build_system_prompt(
            base_prompt,
            effective_type_check_stubs,
            external_functions=None if type_check_stubs else external_functions,
        )
        self._external_functions = external_functions
        self._type_check_stubs = effective_type_check_stubs
        self._max_duration_secs = max_duration_secs
        self._type_check = type_check
        self.tools = [
            make_execute_python(
                backend=backend,
                external_functions=external_functions,
                type_check_stubs=effective_type_check_stubs,
                max_duration_secs=max_duration_secs,
                type_check=type_check,
            )
        ]

    # ---- system prompt injection ---------------------------------------

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        new_system_message = _append_to_system_message(request.system_message, self._system_prompt)
        return handler(request.override(system_message=new_system_message))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        new_system_message = _append_to_system_message(request.system_message, self._system_prompt)
        return await handler(request.override(system_message=new_system_message))


def _resolve_type_check_stubs(
    *,
    external_functions: dict[str, Callable[..., Any]] | None,
    type_check_stubs: str | None,
) -> str | None:
    if type_check_stubs:
        return type_check_stubs
    return _build_external_function_stubs(external_functions)


def _build_external_function_stubs(
    external_functions: dict[str, Callable[..., Any]] | None,
) -> str | None:
    if not external_functions:
        return None
    external_imports: set[str] = set()
    stubs = [
        _build_external_function_stub(name, fn, external_imports)
        for name, fn in external_functions.items()
    ]
    imports = [
        "from typing import Any, Annotated, Callable, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, Union",
        *[f"import {module}" for module in sorted(external_imports)],
    ]
    return "\n".join(imports) + "\n\n" + "\n".join(stubs)


def _build_external_function_stub(
    name: str,
    fn: Callable[..., Any],
    external_imports: set[str],
) -> str:
    prefix = "async def" if inspect.iscoroutinefunction(fn) else "def"
    try:
        signature = inspect.signature(fn, eval_str=True)
    except (TypeError, ValueError):
        return f"{prefix} {name}(*args: Any, **kwargs: Any) -> Any: ..."

    params = _format_signature_params(signature, external_imports)
    return_type = _format_annotation(signature.return_annotation, external_imports)
    return f"{prefix} {name}({params}) -> {return_type}: ..."


def _format_signature_params(
    signature: inspect.Signature,
    external_imports: set[str],
) -> str:
    params: list[str] = []
    saw_keyword_only = False
    positional_only_count = sum(
        1 for p in signature.parameters.values() if p.kind is inspect.Parameter.POSITIONAL_ONLY
    )
    positional_only_seen = 0

    for param in signature.parameters.values():
        if param.kind is inspect.Parameter.KEYWORD_ONLY and not saw_keyword_only:
            params.append("*")
            saw_keyword_only = True

        params.append(_format_signature_param(param, external_imports))

        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional_only_seen += 1
            if positional_only_seen == positional_only_count:
                params.append("/")

    return ", ".join(params)


def _format_signature_param(param: inspect.Parameter, external_imports: set[str]) -> str:
    name = param.name
    if param.kind is inspect.Parameter.VAR_POSITIONAL:
        name = f"*{name}"
    elif param.kind is inspect.Parameter.VAR_KEYWORD:
        name = f"**{name}"

    text = f"{name}: {_format_annotation(param.annotation, external_imports)}"
    if param.default is not inspect.Parameter.empty:
        text += " = ..."
    return text


def _format_annotation(annotation: Any, external_imports: set[str]) -> str:
    if annotation is inspect.Signature.empty or annotation is inspect.Parameter.empty:
        return "Any"
    if isinstance(annotation, str):
        return annotation
    _collect_annotation_imports(annotation, external_imports)
    return inspect.formatannotation(annotation)


def _collect_annotation_imports(annotation: Any, external_imports: set[str]) -> None:
    if annotation in (None, Any):
        return

    module = getattr(annotation, "__module__", "")
    if module not in ("", "builtins", "typing", "types"):
        external_imports.add(module.split(".", 1)[0])

    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        _collect_annotation_imports(origin, external_imports)

    for arg in getattr(annotation, "__args__", ()):
        if arg is Ellipsis:
            continue
        _collect_annotation_imports(arg, external_imports)

    if isinstance(annotation, UnionType):
        for arg in annotation.__args__:
            _collect_annotation_imports(arg, external_imports)


def _build_system_prompt(
    base_prompt: str,
    type_check_stubs: str | None,
    *,
    external_functions: dict[str, Callable[..., Any]] | None = None,
) -> str:
    if not type_check_stubs:
        return base_prompt
    external_functions_header = _build_external_functions_header(external_functions)
    return f"""{base_prompt}

{external_functions_header}

```python
{type_check_stubs.strip()}
```
"""


def _build_external_functions_header(
    external_functions: dict[str, Callable[..., Any]] | None,
) -> str:
    base = (
        "External functions: the following host-provided functions/types are available "
        "inside `python_repl` as global names. Call them directly; do not redefine or "
        "import them. External functions are resolved only when a name is not a builtin, "
        "import, or local definition."
    )
    if not external_functions:
        return f"{base} Call async functions with `await`; sync functions can be called normally."

    has_async = any(inspect.iscoroutinefunction(fn) for fn in external_functions.values())
    has_sync = any(not inspect.iscoroutinefunction(fn) for fn in external_functions.values())
    if has_async and has_sync:
        return (
            f"{base} Async functions (`async def`) must be called with `await`, "
            "e.g. `result = await fetch_value(arg)`. Sync functions (`def`) are called "
            "normally, e.g. `result = double(arg)`."
        )
    if has_async:
        return (
            f"{base} All external functions are async: call them with `await`, "
            "e.g. `result = await fetch_value(arg)`. Calling without `await` returns "
            "an unresolved future, not the value."
        )
    return (
        f"{base} All external functions are synchronous: call them normally, "
        "e.g. `result = double(arg)`."
    )


def _wrap_external_functions_in_context(
    external_functions: dict[str, Callable[..., Any]] | None,
) -> dict[str, Callable[..., Any]] | None:
    """Run external functions inside the current LangGraph context."""
    if external_functions is None:
        return None

    ctx = contextvars.copy_context()
    wrapped: dict[str, Callable[..., Any]] = {}
    for name, fn in external_functions.items():
        if inspect.iscoroutinefunction(fn):

            async def async_wrapper(
                *args: Any, __fn: Callable[..., Any] = fn, **kwargs: Any
            ) -> Any:
                task = ctx.run(lambda: asyncio.create_task(__fn(*args, **kwargs)))
                return await task

            wrapped[name] = async_wrapper
        else:

            def sync_wrapper(*args: Any, __fn: Callable[..., Any] = fn, **kwargs: Any) -> Any:
                return ctx.run(__fn, *args, **kwargs)

            wrapped[name] = sync_wrapper
    return wrapped

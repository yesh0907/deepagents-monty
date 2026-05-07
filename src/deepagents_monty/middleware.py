"""MontyCodeMiddleware: a Deep Agents middleware that adds a Monty-backed
``execute_python`` tool sharing the agent's filesystem.

See README.md for the design discussion. The short version:

- ``backend`` is required (matches SkillsMiddleware / MemoryMiddleware; this
  is a consumer of shared filesystem, not a provider).
- ``type_check=True`` by default (catches type errors at parse-time for ~15-30ms).
- The filesystem bridge uses the sync backend contract; optional
  ``external_functions`` can expose sync or async host callables.
"""

from __future__ import annotations

import contextvars
import inspect
from collections.abc import Callable
from typing import Any

import pydantic_monty as pm
from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic_monty import Monty, ResourceLimits

from .bridge import DeepAgentBackendOS

__all__ = ["MontyCodeMiddleware", "make_execute_python"]


EXECUTE_PYTHON_DESCRIPTION = """\
Run Python in a secure Monty interpreter.

Files: read/write via pathlib.Path. Paths must be absolute (start with /).
These files are the SAME ones ls/read_file/write_file/edit_file see.

Limitations:
- Subset of Python only: no classes, no match statements, no generators,
  no context managers (yet).
- No third-party libraries (pandas, requests, etc.).
- Files cannot be deleted or renamed - overwrite with empty content instead.
- Directories are implicit (they exist only when they contain files).

The return value is the last expression evaluated. Use print() for debugging;
stdout/stderr are captured and returned.
"""


_MONTY_SYSTEM_PROMPT = """\
## Code execution (`execute_python`)

You have access to `execute_python` for running Python code in a secure \
sandboxed interpreter. This is the right tool when a task is easier to \
express as code than as a sequence of filesystem tool calls - loops, \
conditionals, data transforms, JSON parsing, etc.

Filesystem sharing: code run via `execute_python` reads and writes files \
through `pathlib.Path`, and sees the SAME filesystem as `ls`, `read_file`, \
`write_file`, `edit_file`, `glob`, and `grep`. Paths must be absolute \
(start with `/`).

Limitations to be aware of:
- This is a Python subset: no class definitions, no match statements, no \
context managers (yet).
- No third-party libraries (pandas, requests, numpy, etc.). Only core \
syntax and a small stdlib subset (`sys`, `typing`, `asyncio`, `re`, \
`datetime`, `json`).
- Files cannot be deleted or renamed. To "delete", overwrite with empty \
content. Directories are implicit - they exist only when they contain files.
- Use `print()` for debugging; stdout is captured and returned.
- The last top-level expression is the return value.
"""


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


def make_execute_python(
    *,
    backend: BackendProtocol,
    external_functions: dict[str, Callable[..., Any]] | None = None,
    type_check_stubs: str | None = None,
    max_duration_secs: float = 10.0,
    type_check: bool = True,
) -> StructuredTool:
    """Build a standalone ``execute_python`` tool.

    Most users should prefer :class:`MontyCodeMiddleware`, which also handles
    system-prompt injection. This helper is for advanced setups that want to
    register the tool manually (e.g. alongside custom middleware composition).
    """

    async def execute_python(code: str, runtime: ToolRuntime) -> str:
        fs = DeepAgentBackendOS(backend)
        wrapped_external_functions = _wrap_external_functions_in_context(external_functions)
        try:
            m = Monty(code, type_check=type_check, type_check_stubs=type_check_stubs)
        except pm.MontySyntaxError as e:
            return f"SyntaxError: {e}"
        except pm.MontyTypingError as e:
            return f"TypeError: {e}"

        stdout_chunks: list[str] = []

        def capture_print(stream: str, text: str) -> None:
            stdout_chunks.append(text)

        try:
            result = await m.run_async(
                os=fs,
                external_functions=wrapped_external_functions,
                limits=ResourceLimits(max_duration_secs=max_duration_secs),
                print_callback=capture_print,
            )
        except pm.MontyRuntimeError as e:
            stdout = "".join(stdout_chunks)
            tail = f"\n--stdout--\n{stdout}" if stdout else ""
            return f"RuntimeError: {e}{tail}"
        except pm.MontyError as e:
            return f"MontyError: {type(e).__name__}: {e}"

        stdout = "".join(stdout_chunks)
        parts = [f"return: {result!r}"]
        if stdout:
            parts.append(f"--stdout--\n{stdout}")
        return "\n".join(parts)

    return StructuredTool.from_function(
        coroutine=execute_python,
        name="execute_python",
        description=EXECUTE_PYTHON_DESCRIPTION,
    )


class MontyCodeMiddleware(AgentMiddleware):
    """Adds an ``execute_python`` tool backed by the Monty interpreter.

    Code executed via this tool shares the filesystem with any other
    BackendProtocol-using middleware (e.g. ``FilesystemMiddleware``): a file
    written through ``execute_python`` is readable via ``read_file``, and
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
                ``execute_python`` sees the same files as ``read_file``,
                ``write_file``, etc. We follow the pattern of
                ``SkillsMiddleware`` and ``MemoryMiddleware`` (required
                backend), rather than ``FilesystemMiddleware`` (defaults to
                ``StateBackend()``), because ``MontyCodeMiddleware`` is a
                *consumer* of the shared filesystem - silently defaulting
                to a new backend would create two disjoint filesystems
                and break cross-tool file sharing without warning.
            system_prompt: Override for the default Monty system prompt
                that describes ``execute_python`` to the model.
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
        base_prompt = system_prompt if system_prompt is not None else _MONTY_SYSTEM_PROMPT
        self._system_prompt = _build_system_prompt(base_prompt, type_check_stubs)
        self._external_functions = external_functions
        self._type_check_stubs = type_check_stubs
        self._max_duration_secs = max_duration_secs
        self._type_check = type_check
        self.tools = [
            make_execute_python(
                backend=backend,
                external_functions=external_functions,
                type_check_stubs=type_check_stubs,
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


def _build_system_prompt(base_prompt: str, type_check_stubs: str | None) -> str:
    if not type_check_stubs:
        return base_prompt
    return f"""{base_prompt}

External functions: the following host-provided functions/types are available \
inside `execute_python` as global names. Call async functions with `await`; \
sync functions can be called normally. External functions are resolved only \
when a name is not a builtin, import, or local definition.

```python
{type_check_stubs.strip()}
```
"""


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

            async def async_wrapper(*args: Any, __fn: Callable[..., Any] = fn, **kwargs: Any) -> Any:
                return await ctx.run(__fn, *args, **kwargs)

            wrapped[name] = async_wrapper
        else:

            def sync_wrapper(*args: Any, __fn: Callable[..., Any] = fn, **kwargs: Any) -> Any:
                return ctx.run(__fn, *args, **kwargs)

            wrapped[name] = sync_wrapper
    return wrapped

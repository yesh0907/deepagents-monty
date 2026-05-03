# deepagents-monty

`MontyCodeMiddleware` for [Deep Agents](https://github.com/langchain-ai/deepagents): adds a secure `execute_python` tool backed by Pydantic's [Monty](https://github.com/pydantic/monty) sandboxed Python interpreter, with files shared across Monty and the rest of the agent.

When the LLM writes Python code, the code runs in a microsecond-startup sandbox with zero host capabilities except what you explicitly grant. It can read and write files through `pathlib.Path`, and those files are the **same** files that `read_file`, `write_file`, `ls`, `glob`, `grep`, and `edit_file` see.

## Install

```bash
uv add 'deepagents>=0.5.3' 'pydantic-monty>=0.0.11'
```

## Usage

```python
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents_monty import MontyCodeMiddleware

# ONE backend, shared between FilesystemMiddleware and MontyCodeMiddleware.
backend = StateBackend()

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,                              # consumed by FilesystemMiddleware
    middleware=[MontyCodeMiddleware(backend=backend)],
)

result = await agent.ainvoke({
    "messages": [{"role": "user", "content":
        "Find all Python files larger than 1000 bytes and list their sizes."
    }]
})
```

The model can now call `execute_python` with code like:

```python
from pathlib import Path

sizes = []
for p in Path('/').iterdir():
    if str(p).endswith('.py'):
        content = p.read_text()
        if len(content) > 1000:
            sizes.append((str(p), len(content)))
sorted(sizes, key=lambda x: -x[1])
```

— and the files it sees are the same files a subsequent `read_file` call would see.

## How it works

Three pieces:

1. **`DeepAgentBackendOS(AbstractOS)`** — projects a Deep Agents `BackendProtocol` as a Monty virtual filesystem. Monty's VM calls `path_read_bytes`, `path_write_text`, etc.; we route those to `backend.read`, `backend.write`, etc.

2. **`MontyCodeMiddleware(AgentMiddleware)`** — wraps the bridge up as a proper middleware. Registers the `execute_python` tool, injects a system prompt describing its capabilities and limits, accepts `backend` and a few knobs in its constructor.

3. **`execute_python` tool** — the LLM-facing surface. Accepts Python code as a string, runs it in Monty with the backend-bridged filesystem, returns the last expression and captured stdout.

## Design decisions

### `backend` is required (no silent default)

`FilesystemMiddleware` defaults to `StateBackend()` because it's the *provider* of file tools. `MontyCodeMiddleware` is a *consumer* of the shared filesystem — if it silently created its own backend, `execute_python` would be writing to a different filesystem than `read_file` reads from, and the whole point of the middleware is defeated without warning.

Matches the pattern of `SkillsMiddleware` and `MemoryMiddleware`, which also require a backend.

### Type checking defaults to on

`type_check=True` by default. Monty uses `ty` (the same type checker Astral ships with Ruff) at parse time. Costs ~15-30ms at parse, zero at runtime, and gives the model a clear diagnostic on type errors before the code starts running so it can retry on the same turn. Matches Pydantic AI's own code-mode default. Opt out with `MontyCodeMiddleware(backend=..., type_check=False)`.

### Delete and rename are not supported

`Path.unlink()`, `Path.rmdir()`, and `Path.rename()` raise `PermissionError` with a helpful message. Reasons:

1. Deep Agents' `BackendProtocol` has no `delete` method. There's no obvious mapping.
2. For the usual "replace a file" case, write-with-overwrite works fine — the bridge falls back to `backend.edit()` when `backend.write()` refuses an overwrite.
3. To "delete", overwrite with empty content.

### Directories are implicit

Deep Agents' filesystem is a flat namespace with implicit directories. `path_mkdir` is a no-op. `Path('/a/b').write_text('x')` creates `/a/b` and "directory" `/a` is then visible to `Path('/').iterdir()`.

## Sync-only backend by design

The bridge calls backend methods **synchronously**. All built-in Deep Agents backends (`StateBackend`, `StoreBackend`, `FilesystemBackend`, `CompositeBackend`) expose sync methods and are the expected pairing. Calls from Monty's VM run on its worker thread; the sync backend call blocks that thread for microseconds and returns.

### Why not async?

Monty intentionally splits host-callback into two channels:

| Channel | Sync support | Async support | Mechanism |
|---|---|---|---|
| `AbstractOS` (what this bridge uses) | ✓ | ✗ by design | Direct callback from worker thread |
| `external_functions` (Monty's alternative) | ✓ | ✓ native | Suspend/resume via `Monty.start()` → `MontySnapshot.resume()` |

The canonical Monty pattern for async is to expose host operations as `external_functions` with coroutine values. Monty's VM pauses at each external call, control returns to the host's event loop, and the VM is resumed with the result. From the Pydantic team:

> Because Monty uses a suspend-and-resume model rather than traditional callbacks, the entire interpreter state can be serialized to a database when a tool call is in progress. If a tool takes minutes, hours, or even days to return, you do not need to keep the interpreter sitting in memory waiting.

### What if I have an async-only backend?

If you build a remote backend (e.g. `S3Backend`, `PostgresBackend`) that exposes only `aread`/`awrite` and has no sync counterparts, do **not** try to drive it through `AbstractOS`.

Calling `asyncio.run_coroutine_threadsafe(coro, main_loop)` from inside a `path_*` callback **deadlocks**. The reason: when you `await monty.run_async()`, Monty returns a PyO3 Future that pins the main Python thread while its worker executes. The main thread is no longer processing scheduled coroutines, so a coroutine scheduled via `run_coroutine_threadsafe(coro, main_loop)` never runs. The worker thread blocks forever waiting for a result the main thread will never produce.

A dedicated-loop-thread workaround does exist and does unblock — the bridge can run async coroutines on a separate asyncio loop on its own daemon thread, so Monty's worker blocks on *that* thread while the main loop stays responsive. But empirically it pays a consistent **~3.8s first-call warmup cost** (PyO3/tokio cross-thread initialization) that isn't worth paying. Subsequent calls are fast (~50ms each). Throughout, the main loop does stay responsive, so it's a latency problem, not a correctness problem — but it's still slow enough to be painful, and it's not the idiomatic Monty pattern.

**The idiomatic alternative is to write a complementary middleware that uses `external_functions`**:

```python
external_functions = {
    "read_file":  async def read_file(path): return await backend.aread(path),
    "write_file": async def write_file(path, content): return await backend.awrite(path, content),
    "ls":         async def ls(path): return await backend.als(path),
    # etc.
}
```

The LLM-facing ergonomics change — `await read_file('/x')` instead of `Path('/x').read_text()` — but async works natively with zero thread-bridging and no PyO3 Future pinning issues. This is also the approach Pydantic AI's own `CodeExecutionToolset` took (see their PR [pydantic-ai#4153](https://github.com/pydantic/pydantic-ai/pull/4153)).

This middleware stays sync-only. If you need async-remote, build the external_functions variant alongside it.

## Threading note

Monty's VM calls `path_*` methods from a worker thread, not the caller's async thread. LangGraph's `StateBackend` reads state via `langgraph.config.get_config()`, which is a ContextVar lookup — and ContextVars are thread-local, so the worker thread can't see the graph's config by default.

The bridge handles this: in `DeepAgentBackendOS.__init__`, it calls `contextvars.copy_context()` to snapshot the current LangGraph context, then wraps every backend call in `self._ctx.run(...)`. The backend sees the right `CONFIG_KEY_READ` / `CONFIG_KEY_SEND` regardless of which thread it's called from.

You don't need to think about this unless you're writing a custom `BackendProtocol` that uses ContextVars for its own state.

## Monty's limitations (pass-through)

`MontyCodeMiddleware` inherits Monty's subset of Python. Current limits in `pydantic-monty` 0.0.15:

- **No class definitions.** LLM-generated code will hit a `SyntaxError` if it writes `class Foo: ...`.
- **No match statements, no generators, no context managers.**
- **No third-party libraries** (`pandas`, `requests`, `numpy`, etc.). Only a small stdlib subset: `sys`, `typing`, `asyncio`, `re`, `datetime`, `json`, `dataclasses`.
- **Deletes and renames blocked** (see above).
- **Binary writes** (`path_write_bytes` with non-UTF-8 data) raise `NotImplementedError`. Base64 routing is a future extension.

The system prompt describes these limits so the model can plan around them.

## Tests

```bash
uv run python test_spike.py
```

Runs three test groups with 13 subtests: bridge unit tests, end-to-end agent test with scripted fake LLM, middleware surface test (tools registered, system prompt injected, backend required, type-checking defaults). No API keys needed.

## Credits

- [Pydantic](https://pydantic.dev) for Monty.
- [LangChain](https://github.com/langchain-ai/deepagents) for Deep Agents.

## References

- **Monty**: [pydantic/monty](https://github.com/pydantic/monty), [pypi](https://pypi.org/project/pydantic-monty/), [docs](https://pydantic-monty.mintlify.app/).
- **Deep Agents**: [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents).
- **Pydantic AI CodeExecutionToolset** (for reference on the `external_functions`-based pattern): [pydantic-ai#4153](https://github.com/pydantic/pydantic-ai/pull/4153).
- **Issue #190** in `pydantic/monty` — describes the `ReplProgress` variants (`Complete`, `FunctionCall`, `OsCall`, `ResolveFutures`) that underpin Monty's suspend/resume model.

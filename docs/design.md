# Design Notes

`deepagents-monty` has three main pieces:

1. `DeepAgentBackendOS(AbstractOS)` projects a Deep Agents `BackendProtocol` as
   a Monty virtual filesystem. Monty's VM calls methods such as
   `path_read_bytes` and `path_write_text`; the bridge routes those calls to
   `backend.read`, `backend.write`, and related backend methods.
2. `MontyCodeMiddleware(AgentMiddleware)` registers the `python_repl` tool,
   injects a system prompt that describes its capabilities, and accepts the
   backend plus configuration knobs.
3. The `python_repl` tool runs model-written Python in Monty and returns the
   last expression value plus captured stdout.

## Backend Is Required

`MontyCodeMiddleware` requires `backend`.

`FilesystemMiddleware` defaults to `StateBackend()` because it provides file
tools. `MontyCodeMiddleware` consumes the shared filesystem. If it silently
created its own backend, `python_repl` would read and write a different
filesystem from `read_file`, defeating the main purpose of the middleware.

This matches `SkillsMiddleware` and `MemoryMiddleware`, which also require a
backend.

## Type Checking Defaults To On

`type_check=True` by default. Monty uses `ty` at parse time, which adds a small
parse-time cost and no runtime cost. The benefit is that the model gets a clear
diagnostic before code starts running, so it can retry in the same turn.

Disable it with:

```python
MontyCodeMiddleware(backend=backend, type_check=False)
```

## REPL State

`python_repl` preserves variables, imports, and function definitions between
calls. With Pydantic Monty 0.0.19, each invocation checks out an isolated
subprocess session, restores the prior idle-session dump from LangGraph state,
executes the snippet, and stores a fresh dump. Passing `restart=True` skips the
restore and starts from a fresh session.

## Worker Lifecycle

Pydantic Monty 0.0.19 executes code in subprocess workers. The middleware opens
an `AsyncMonty` pool for the tool invocation and checks out one session. A
worker crash or host-side request timeout does not terminate the agent process;
the error is returned to the model and the last good persisted session dump is
left intact.

## Parallel Tool Calls

`python_repl` rejects parallel tool calls. If the model emits `python_repl` in
the same assistant message as another tool call, the tool returns a
`RuntimeError` asking the model to call `python_repl` by itself and wait for the
result.

This keeps REPL state and filesystem effects ordered and easier to reason about.

## Delete And Rename

`Path.unlink()`, `Path.rmdir()`, and `Path.rename()` raise `PermissionError`.

Reasons:

- Deep Agents' `BackendProtocol` has no delete method.
- Replacing a file is supported through write-with-overwrite.
- To "delete", overwrite the file with empty content.

## Implicit Directories

Deep Agents' filesystem is a flat namespace with implicit directories.
`path_mkdir` is a no-op. Writing `/a/b.txt` makes `/a` visible to directory
iteration because it contains a file.

## Sync Backend Bridge

The filesystem bridge calls backend methods synchronously. Built-in Deep Agents
backends such as `StateBackend`, `StoreBackend`, `FilesystemBackend`, and
`CompositeBackend` expose sync methods and are the expected pairing.

Monty intentionally separates two host-callback channels:

| Channel | Sync support | Async support | Mechanism |
| --- | --- | --- | --- |
| `AbstractOS` | yes | no | subprocess request serviced by a host callback |
| `external_functions` | yes | yes | exposed through Monty's `external_lookup` |

If you build an async-only backend, expose it through `external_functions`
instead of trying to drive it through `AbstractOS`:

```python
async def read_file(path: str) -> str:
    return await backend.aread(path)


async def write_file(path: str, content: str) -> None:
    await backend.awrite(path, content)


middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={
        "read_file": read_file,
        "write_file": write_file,
    },
)
```

The model-facing ergonomics become `await read_file("/x")` instead of
`Path("/x").read_text()`, but async host operations work natively.

## Callback Context

Monty's VM runs in a subprocess and sends `path_*` operations back to host-side
callbacks. LangGraph's `StateBackend` reads state through
`langgraph.config.get_config()`, which is a `ContextVar` lookup.

`DeepAgentBackendOS.__init__` calls `contextvars.copy_context()` and runs every
backend call inside that captured context. The backend sees the right
`CONFIG_KEY_READ` and `CONFIG_KEY_SEND` during callback dispatch.

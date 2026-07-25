# Pydantic Monty 0.0.19 integration research

Research date: 2026-07-25

## Release identity

The latest stable release is **`pydantic-monty 0.0.19`**, published on
2026-07-24 (GitHub: 09:12 UTC; PyPI uploads began 09:56 UTC). It requires
Python 3.10+ and now installs an exactly matched
`pydantic-monty-runtime==0.0.19` worker binary.

Primary sources:

- [Official v0.0.19 release and complete change list](https://github.com/pydantic/monty/releases/tag/v0.0.19)
- [Official v0.0.18...v0.0.19 comparison](https://github.com/pydantic/monty/compare/v0.0.18...v0.0.19)
- [PyPI project metadata](https://pypi.org/pypi/pydantic-monty/json)
- [Tagged Python API guide](https://github.com/pydantic/monty/blob/v0.0.19/crates/monty-python/README.md)
- [Tagged public Python exports](https://github.com/pydantic/monty/blob/v0.0.19/crates/monty-python/python/pydantic_monty/__init__.py)

## Immediate compatibility finding

This repository is **not compatible with 0.0.19**, despite declaring
`pydantic-monty>=0.0.17`.

- `uv.lock` still selects 0.0.17, masking the break in the locked development
  environment.
- A clean environment with 0.0.19 fails while importing
  `deepagents_monty.middleware`: `MontyRepl` is no longer exported.
- `MontyRepl`, module-level `load_repl_snapshot` / `load_snapshot`, and the old
  async helper functions were removed. `Monty` is now a subprocess pool;
  `pool.checkout()` returns a `MontySession`, and `AsyncMonty` /
  `AsyncMontySession` are the async equivalents. This redesign provides crash
  isolation and worker replacement ([PR #500](https://github.com/pydantic/monty/pull/500)).
- `ResourceLimits` is now a `TypedDict`, so
  `ResourceLimits(max_duration_secs=...)` must become a dictionary. Its values
  may be `None`, and `max_allocations` was removed
  ([PR #611](https://github.com/pydantic/monty/pull/611)).
- `feed_run(..., external_functions=...)` becomes
  `session.feed_run(..., external_lookup=...)`. The lookup may contain either
  callables or plain host values
  ([PR #520](https://github.com/pydantic/monty/pull/520)).
- Idle REPL state is now persisted with `session.dump()` and restored on a
  fresh session with `session.load_session(blob)`. Suspended executions use
  `load_snapshot` instead. `feed_start` was restored
  ([PR #507](https://github.com/pydantic/monty/pull/507)) and snapshots gained
  `resume_auto()` ([PR #527](https://github.com/pydantic/monty/pull/527)).
- `AbstractOS` remains supported by `feed_run(os=...)`; the only tagged
  `os_access.py` protocol spelling change is internal `"Open"` to `"open"`, so
  the bridge methods themselves do not need a structural rewrite.

## Release items worth incorporating

### Required migration

1. Migrate execution atomically to the new pool/session API and require
   `pydantic-monty>=0.0.19`. Refresh the lock file in the same change.
2. Decide pool lifetime explicitly. A middleware-owned `AsyncMonty` pool is the
   natural fit for async DeepAgents calls and reuses warm workers; creating a
   pool per tool call is simpler but forfeits pooling. Continue storing an idle
   session dump in LangGraph state if conversation persistence is required.
3. Map the existing duration option to
   `limits={"max_duration_secs": value}` and add a separate pool
   `request_timeout` backstop. Monty documents duration as cumulative sandbox
   execution time, while `request_timeout` kills a hung worker at the host
   boundary.
4. Handle the new `MontyCrashedError` (including timeout metadata) and
   `MontyConversionError` as model-visible failures. Test that a crashed worker
   does not corrupt persisted conversation state.
5. Revalidate context propagation. External callbacks and `AbstractOS` now
   cross a subprocess protocol as well as a worker boundary; the existing
   worker-thread explanation and assumptions in `bridge.py` are stale even if
   `contextvars.copy_context()` remains useful on the host callback thread.

### User-visible capability and prompt updates

The 0.0.19 release adds partial user-defined classes
([PR #515](https://github.com/pydantic/monty/pull/515)), class decorators
([PR #582](https://github.com/pydantic/monty/pull/582)), transitive closures
([PR #516](https://github.com/pydantic/monty/pull/516)), `unicodedata`
([PR #522](https://github.com/pydantic/monty/pull/522)), string/bytes
encode/decode codecs ([PR #523](https://github.com/pydantic/monty/pull/523)),
pytest-style assert messages ([PR #556](https://github.com/pydantic/monty/pull/556)),
`iter(callable, sentinel)` ([PR #581](https://github.com/pydantic/monty/pull/581)),
and arbitrary-iterable starred unpacking
([PR #589](https://github.com/pydantic/monty/pull/589)).

Accordingly, this package's prompt should stop saying that classes and context
managers are wholly unavailable, add `unicodedata`, and describe the narrower
remaining limits: no inheritance/metaclasses, no function/method decorators,
no generators, no `async with`, and no `match`. These claims should be covered
by execution tests rather than copied only into prompt text.

### Security and operational improvements to expose/test

- Worker subprocess isolation means adversarial crashes no longer endanger the
  host Python process ([PR #500](https://github.com/pydantic/monty/pull/500)).
- Async memory limits were added
  ([PR #504](https://github.com/pydantic/monty/pull/504)).
- Print collectors are capped to prevent unbounded host memory use
  ([PR #558](https://github.com/pydantic/monty/pull/558)).
- Mount handling moved host-side
  ([PR #576](https://github.com/pydantic/monty/pull/576)); retain the custom
  `AbstractOS` bridge for the DeepAgents virtual backend rather than replacing
  it with host-directory mounts.

## Suggested discussion order

First address the currently-open dependency incompatibility, then choose the
pool/session lifetime and state-dump design. After that, update error mapping
and resource controls, and finally refresh the advertised language subset and
tests. This keeps the compatibility migration separate from optional capability
polish.

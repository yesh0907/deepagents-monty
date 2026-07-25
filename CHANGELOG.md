# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Require `pydantic-monty>=0.0.19` and migrate execution from the removed
  `MontyRepl` API to subprocess-backed `AsyncMonty` pools and sessions.
- Restore and persist REPL state with session dumps, use `external_lookup` for
  host functions, and adopt dictionary-style resource limits.
- Add `request_timeout_secs` as a host-side worker timeout and report worker
  crashes, timeouts, and conversion failures as model-visible errors.
- Refresh the advertised Python subset for partial classes and context managers
  plus the new `unicodedata` support.

## [0.2.0] - 2026-05-30

### Added

- `MontyCodeMiddleware` now accepts an `append_system_prompt` parameter that
  appends extra guidance after the base prompt (separated by a blank line),
  instead of forcing consumers to either fully replace the default prompt via
  `system_prompt` or import the private `_MONTY_SYSTEM_PROMPT`. `system_prompt`
  and `append_system_prompt` compose independently, and any
  `external_functions` type stubs are still appended after the composed base.
- `MONTY_SYSTEM_PROMPT` is now exported publicly (alias of the private
  `_MONTY_SYSTEM_PROMPT`, which is retained for backward compatibility) so
  advanced users can introspect or compose against the default prompt without
  touching a private symbol.
- `build_system_prompt(*, system_prompt=None, append=None)` helper to compose
  the base prompt from a custom base and/or appended guidance.

## [0.1.1] - 2026-05-30

### Fixed

- `DeepAgentBackendOS.path_read_bytes` / `path_read_text` no longer truncate
  large files. The backend's `read` defaults to `limit=2000` LINES (a display
  cap for the agent's `read_file` tool); that cap was leaking into `pathlib`
  reads inside the Monty sandbox, so `Path(p).read_text()` returned only the
  first 2000 lines. Large offloaded tool results (e.g. a ~300-row indented JSON
  array) were silently cut off, breaking `json.loads`. Reads now paginate by
  line offset and concatenate every window, returning the whole file. Binary
  (base64) reads are unaffected - backends return those whole regardless of the
  line cap.

## [0.1.0] - 2026-05-28

### Added

- `DeepAgentBackendOS` - projects a Deep Agents `BackendProtocol` as a Monty
  `AbstractOS`, bridging pathlib operations inside Monty code to backend reads
  and writes.
- `MontyCodeMiddleware` - a Deep Agents `AgentMiddleware` that registers an
  `python_repl` tool backed by Monty and injects a descriptive system prompt.
- `make_execute_python` - standalone tool factory for advanced users who want
  the tool without the middleware machinery.

### Design decisions documented

- Backend required (consumer-not-provider, matching `SkillsMiddleware`).
- Type checking on by default via Monty's bundled `ty`.
- Sync-only backend contract - see README for the tradeoff vs. Monty's
  `external_functions` channel for genuinely async backends.
- ContextVar propagation from caller thread to Monty's worker thread for
  LangGraph compatibility.

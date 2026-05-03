# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-19

### Added

- `DeepAgentBackendOS` - projects a Deep Agents `BackendProtocol` as a Monty
  `AbstractOS`, bridging pathlib operations inside Monty code to backend reads
  and writes.
- `MontyCodeMiddleware` - a Deep Agents `AgentMiddleware` that registers an
  `execute_python` tool backed by Monty and injects a descriptive system prompt.
- `make_execute_python` - standalone tool factory for advanced users who want
  the tool without the middleware machinery.

### Design decisions documented

- Backend required (consumer-not-provider, matching `SkillsMiddleware`).
- Type checking on by default via Monty's bundled `ty`.
- Sync-only backend contract - see README for the tradeoff vs. Monty's
  `external_functions` channel for genuinely async backends.
- ContextVar propagation from caller thread to Monty's worker thread for
  LangGraph compatibility.

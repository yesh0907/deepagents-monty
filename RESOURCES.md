# DeepAgents Monty Maintenance Resources

## Knowledge

- [Pydantic Monty v0.0.19 release](https://github.com/pydantic/monty/releases/tag/v0.0.19)
  Canonical release inventory. Use first when separating API migrations, runtime changes, and new language capabilities.
- [Pydantic Monty v0.0.19 Python API guide](https://github.com/pydantic/monty/blob/v0.0.19/crates/monty-python/README.md)
  Primary explanation of pools, sessions, snapshots, resource limits, async execution, and crash isolation.
- [Pydantic Monty v0.0.19 public Python exports](https://github.com/pydantic/monty/blob/v0.0.19/crates/monty-python/python/pydantic_monty/__init__.py)
  Use to verify exported types and `ResourceLimits` rather than assuming old symbols still exist.
- [Pydantic Monty PR #500: subprocess pools](https://github.com/pydantic/monty/pull/500)
  Architectural source for the move from `MontyRepl` to crash-isolated worker pools.
- [Local v0.0.19 integration research](docs/research/pydantic-monty-0.0.19.md)
  Maintainer-oriented mapping from the upstream release to this package's integration seams.
- [Migration commit `041421b`](https://github.com/yesh0907/deepagents-monty/commit/041421b)
  Concrete implementation showing how the package adopted the new runtime API and protected behavior with tests.

## Wisdom (Communities)

- [Pydantic Monty GitHub discussions and issues](https://github.com/pydantic/monty/issues)
  Use when runtime behavior is ambiguous, undocumented, or appears inconsistent across releases.
- [Deep Agents GitHub repository](https://github.com/langchain-ai/deepagents)
  Use to compare middleware lifecycle and state conventions with the host framework this package integrates.

## Gaps

- There is no published compatibility contract between Pydantic Monty and
  third-party middleware packages; executable integration tests remain the
  authoritative safety net.

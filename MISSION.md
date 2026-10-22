# Mission: Maintain DeepAgents Monty

## Why
Maintain `deepagents-monty` safely as Pydantic Monty evolves, with enough
understanding of the underlying runtime to recognize compatibility breaks,
choose appropriate integration designs, and prevent subtle state or security
regressions.

## Success looks like
- Explain how Monty's pool, worker, session, and snapshot concepts map onto the middleware.
- Review an upstream Monty release and identify required package changes.
- Modify execution, persistence, resource limits, callbacks, and error handling confidently.
- Design regression tests that protect DeepAgents-specific behavior across Monty upgrades.

## Constraints
- Lessons should stay grounded in the actual `deepagents-monty` codebase.
- Prefer primary Pydantic Monty sources and executable tests over remembered behavior.
- Keep each lesson short enough to complete in one sitting.

## Out of scope
- Implementing broader DeepAgents Code Interpreter parity before the Monty integration is understood.
- Learning Monty's Rust internals unless they materially affect package maintenance.

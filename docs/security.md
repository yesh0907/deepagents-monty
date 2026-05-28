# Security Model

`deepagents-monty` executes model-written Python in Pydantic Monty, not in the
host Python interpreter.

By default, sandbox code has:

- no host filesystem access
- no network access
- no access to environment variables
- no arbitrary third-party package imports
- no direct access to the Python objects in your application
- only the virtual filesystem exposed by the Deep Agents backend you pass in

## Filesystem Boundary

Code inside `python_repl` reads and writes files through Monty's `AbstractOS`
interface. `DeepAgentBackendOS` implements that interface by routing operations
to the Deep Agents backend.

This means `Path("/report.txt").read_text()` inside Monty reads the same virtual
file that `read_file("/report.txt")` would read from the agent.

It does not read `/report.txt` from the host machine.

## Host Capabilities

Use `external_functions` to expose additional host operations. These functions
are trusted code and should be treated as the boundary where sandboxed model
code can affect the outside world.

Recommendations:

- expose narrow functions instead of broad clients
- validate paths, IDs, URLs, and other model-controlled inputs
- prefer simple JSON-like return values
- avoid returning rich mutable Python objects unless the stubs clearly describe
  the model-facing contract
- make network, database, or filesystem access explicit in function names

## Prompting Is Not A Security Boundary

The middleware injects a system prompt that explains the sandbox's capabilities
and limits to the model. That prompt helps the model use the tool correctly, but
security comes from Monty's execution restrictions and from the host functions
you choose to expose.

## Resource Limits

`max_duration_secs` controls the per-call wall-clock limit for sandboxed code:

```python
MontyCodeMiddleware(backend=backend, max_duration_secs=5.0)
```

Use a lower value for latency-sensitive agents and a higher value for workflows
that intentionally process larger virtual files.

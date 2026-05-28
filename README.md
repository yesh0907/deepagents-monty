# deepagents-monty

[![PyPI](https://img.shields.io/pypi/v/deepagents-monty.svg)](https://pypi.org/project/deepagents-monty/)
[![Python versions](https://img.shields.io/pypi/pyversions/deepagents-monty.svg)](https://pypi.org/project/deepagents-monty/)
[![CI](https://github.com/yesh0907/deepagents-monty/actions/workflows/ci.yml/badge.svg)](https://github.com/yesh0907/deepagents-monty/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`deepagents-monty` adds a secure `python_repl` tool to
[Deep Agents](https://github.com/langchain-ai/deepagents) using Pydantic's
[Monty](https://github.com/pydantic/monty) sandboxed Python interpreter.

Agent-generated Python can inspect and transform the same virtual files used by
`read_file`, `write_file`, `ls`, `glob`, `grep`, and `edit_file`, without giving
that code host filesystem or network access.

## Why use it?

- Run model-written Python in a sandbox instead of on the host.
- Let the model use loops, parsing, aggregation, and data transforms when file
  tools would be awkward.
- Share one Deep Agents backend between the normal file tools and Monty code.
- Expose carefully scoped host capabilities with `external_functions`.

## Install

```bash
uv add deepagents-monty
```

Or with pip:

```bash
pip install deepagents-monty
```

Until the package is published on PyPI, install from this repository:

```bash
uv add 'deepagents-monty @ git+https://github.com/yesh0907/deepagents-monty'
```

## Quickstart

```python
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents_monty import MontyCodeMiddleware

backend = StateBackend()

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    middleware=[MontyCodeMiddleware(backend=backend)],
)

result = await agent.ainvoke({
    "messages": [{
        "role": "user",
        "content": "Find all Python files larger than 1000 bytes and list their sizes.",
    }]
})
```

The model can now call `python_repl` with code like:

```python
from pathlib import Path

sizes = []
for p in Path("/").iterdir():
    if str(p).endswith(".py"):
        content = p.read_text()
        if len(content) > 1000:
            sizes.append((str(p), len(content)))
sorted(sizes, key=lambda x: -x[1])
```

The files visible to `Path("/")` are the same files visible to the Deep Agents
filesystem tools. `python_repl` preserves variables, imports, and function
definitions between calls; pass `restart=True` to reset the REPL.

## Security Model

Monty code runs in a restricted interpreter. By default, it has:

- no host filesystem access
- no network access
- no arbitrary third-party imports
- no access to environment variables
- only the virtual filesystem backed by the Deep Agents backend you provide

Host capabilities must be explicitly exposed through `external_functions`. Treat
those functions as part of the trusted boundary: validate inputs, keep return
values simple, and expose only the operations the model should be allowed to use.

## Limitations

`deepagents-monty` inherits Monty's current Python subset:

- no class definitions
- no match statements, generators, or context managers
- no third-party libraries such as `pandas`, `requests`, or `numpy`
- only a small standard-library subset
- no wall-clock or timing primitives
- no file deletes or renames through `pathlib`
- filesystem bridging expects sync Deep Agents backend methods

See [docs/limitations.md](docs/limitations.md) for the detailed list.

## External Functions

Use `external_functions` when sandboxed code needs a carefully scoped host
capability, such as CSV parsing, an API client, or a domain-specific helper.

```python
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents_monty import MontyCodeMiddleware


def read_csv(path: str) -> list[dict[str, Any]]:
    ...


backend = StateBackend()
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    middleware=[
        MontyCodeMiddleware(
            backend=backend,
            external_functions={"read_csv": read_csv},
        )
    ],
)
```

The model can call the function from `python_repl`:

```python
rows = read_csv("/transactions.csv")
sum(row["Amount"] for row in rows if row["Category"] == "Groceries")
```

Async external functions are supported. Sandbox code must call them with
`await`:

```python
data = await fetch_json("https://example.com/data.json")
```

Function signatures are inferred from Python annotations and added to Monty's
type checker. Pass `type_check_stubs` when the public sandbox contract should be
more precise than the host function signature.

## API

```python
MontyCodeMiddleware(
    *,
    backend,
    system_prompt=None,
    external_functions=None,
    type_check_stubs=None,
    max_duration_secs=10.0,
    type_check=True,
)
```

- `backend`: required Deep Agents backend. Pass the same backend you pass to
  `create_deep_agent(backend=...)`.
- `system_prompt`: optional replacement for the default prompt that describes
  `python_repl` to the model.
- `external_functions`: optional host functions exposed as global names inside
  Monty code.
- `type_check_stubs`: optional Python stub text for external functions and
  model-facing types.
- `max_duration_secs`: per-call wall-clock cap for sandbox execution.
- `type_check`: enables Monty's parse-time type checker. Defaults to `True`.

Advanced users can also build the standalone `python_repl` tool with
`make_execute_python(...)`.

## Examples

### Analyze Agent Files

```python
from pathlib import Path
import json

records = []
for path in Path("/").iterdir():
    if str(path).endswith(".json"):
        records.append(json.loads(path.read_text()))

len(records)
```

### Expose a Safe Reader

```python
def read_transactions() -> list[dict[str, str]]:
    ...

middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={"read_transactions": read_transactions},
)
```

### Use an Async Helper

```python
async def lookup_customer(customer_id: str) -> dict[str, str]:
    ...

middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={"lookup_customer": lookup_customer},
)
```

Sandbox code:

```python
customer = await lookup_customer("cust_123")
customer["segment"]
```

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Build the package locally:

```bash
uv build
uvx twine check dist/*
```

## More Documentation

- [Design notes](docs/design.md)
- [Security model](docs/security.md)
- [External functions](docs/external-functions.md)
- [Limitations](docs/limitations.md)
- [Release process](docs/release.md)

## Credits

- [Pydantic](https://pydantic.dev) for Monty.
- [LangChain](https://github.com/langchain-ai/deepagents) for Deep Agents.

# External Functions

External functions expose explicit host capabilities to Monty code.

They are useful when the sandbox needs something Monty does not provide
directly, such as robust CSV parsing, an API client, a database lookup, or a
domain-specific helper.

## Basic Usage

```python
from typing import Any

from deepagents_monty import MontyCodeMiddleware


def read_csv(path: str) -> list[dict[str, Any]]:
    ...


middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={"read_csv": read_csv},
)
```

Sandbox code can then call:

```python
rows = read_csv("/transactions.csv")
sum(row["Amount"] for row in rows if row["Category"] == "Groceries")
```

## Async Functions

Async functions are supported by Monty's async runtime. Sandbox code must call
them with `await`:

```python
async def fetch_json(url: str) -> dict[str, object]:
    ...


middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={"fetch_json": fetch_json},
)
```

Sandbox code:

```python
data = await fetch_json("https://example.com/data.json")
data["status"]
```

## Type Stubs

Function signatures are inferred from annotations and passed to Monty's type
checker. You can override or enrich that contract with `type_check_stubs`:

```python
middleware = MontyCodeMiddleware(
    backend=backend,
    external_functions={"read_csv": read_csv},
    type_check_stubs="""
from typing import Any

def read_csv(path: str) -> list[dict[str, Any]]:
    \"\"\"Read a CSV file and return one dictionary per row.\"\"\"
    ...
""",
)
```

Use stubs when the host function has a broader internal signature than the
sandbox should rely on, or when the return type needs more model-facing detail.

## Name Resolution

External functions are resolved as otherwise-undefined global names. They do not
override Monty builtins, imports, or names defined inside the executed code.

## Return Values

Prefer JSON-like return values:

- `str`
- `int`
- `float`
- `bool`
- `None`
- `list`
- `dict`

Monty can support richer Python values in some cases, but they are easier for
the model to misuse unless the available methods and attributes are accurately
described in `type_check_stubs`.

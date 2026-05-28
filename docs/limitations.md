# Limitations

`deepagents-monty` inherits Monty's Python subset and adds a few filesystem
constraints from the Deep Agents backend bridge.

Current limitations:

- no class definitions
- no match statements
- no generators
- no context managers
- no third-party libraries such as `pandas`, `requests`, or `numpy`
- no wall-clock or timing primitives such as `asyncio.sleep`,
  `datetime.datetime.now()`, `datetime.date.today()`, or the `time` module
- no `import *` wildcard imports
- no file deletes or renames
- no non-UTF-8 binary writes

Importable standard-library modules currently include:

- `sys`
- `typing`
- `asyncio`
- `math`
- `json`
- `re`
- `datetime`
- `os`
- `pathlib`

## Filesystem Mutations

`Path.unlink()`, `Path.rmdir()`, and `Path.rename()` raise `PermissionError`.
Overwrite files instead:

```python
from pathlib import Path

Path("/old.txt").write_text("")
Path("/new.txt").write_text(Path("/source.txt").read_text())
```

## Directories

Directories are implicit. They exist when they contain files. Creating a
directory with `Path("/x").mkdir()` is a no-op.

## Async Backends

The `pathlib` bridge uses sync backend methods. For async-only host operations,
expose explicit async helpers through `external_functions` and call them with
`await` from sandbox code.

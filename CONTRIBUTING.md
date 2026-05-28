# Contributing

## Setup

```bash
uv sync --all-extras
```

## Checks

Run the core test suite:

```bash
uv run pytest
```

Run linting, formatting checks, and type checking:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Evals

Evaluation code and datasets live under `src/evals`. Install optional eval
dependencies with:

```bash
uv sync --extra evals
```

Run the data-analysis eval harness with:

```bash
uv run python -m evals.data_analysis.run
```

## Release

See [docs/release.md](docs/release.md).

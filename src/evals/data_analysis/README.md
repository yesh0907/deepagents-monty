# Data Analysis Evals

This suite compares a standard Deep Agent with file tools only against the same agent plus `MontyCodeMiddleware`.

For each case and agent variant, the runner creates an isolated `StateBackend` thread and seeds `transactions.csv` into that thread before invocation. The agents see the dataset at `/transactions.csv` without receiving file contents in each user prompt. Expected answers are computed deterministically from `dataset/transactions.sqlite`.

## Setup

Create `.env` at the repository root with:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
```

Only set the keys for providers you plan to run.

## Run

```bash
uv run python -m evals.data_analysis.run
```

Specify models with LangChain-style provider prefixes:

```bash
uv run python -m evals.data_analysis.run --model anthropic:claude-sonnet-4-6
uv run python -m evals.data_analysis.run --model openai:gpt-5.5 --reasoning-effort low
uv run python -m evals.data_analysis.run --model google_genai:gemini-2.5-pro --reasoning-effort medium
```

By default the runner evaluates both agent variants. Use `--variant` to run one side only:

```bash
uv run python -m evals.data_analysis.run --variant all
uv run python -m evals.data_analysis.run --variant no_python
uv run python -m evals.data_analysis.run --variant monty
```

For OpenAI-compatible endpoints, pass a base URL:

```bash
uv run python -m evals.data_analysis.run \
  --model openai:qwen3-coder \
  --base-url http://localhost:1234/v1
```

The runner prints plain progress logs and saves the same log data under `.eval_runs/data_analysis/<run-id>/run.log`. The default JSON report is written beside it as `.eval_runs/data_analysis/<run-id>/results.json`.

Defaults:

- Model: `openai:gpt-5.4-mini` when `--model` is omitted
- Base URL: none
- Reasoning effort: `low` only when `--model` is omitted; otherwise none unless explicitly set
- Variant: `all`
- Output: `.eval_runs/data_analysis/<run-id>/results.json`

You can also override with `--model`, `--base-url`, `--reasoning-effort`, `--variant`, or `--output`.
When you provide `--model`, `--reasoning-effort` is forwarded only if explicitly set, so
custom model runs do not inherit the default OpenAI reasoning setting. The runner maps the
flag to provider-specific LangChain parameters where needed, such as `thinking_level` for
Gemini and `effort` for Anthropic.

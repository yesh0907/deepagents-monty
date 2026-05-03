# Data Analysis Evals

This suite compares a standard Deep Agent with file tools only against the same agent plus `MontyCodeMiddleware`.

The runner seeds `transactions.csv` into each agent's `StateBackend` filesystem once before the eval cases run, so the agents see the dataset at `/transactions.csv` without receiving file contents in each user prompt. Expected answers are computed deterministically from `dataset/transactions.sqlite`.

## Setup

Create `.env` at the repository root with:

```bash
OPENCODE_API_KEY=...
```

Optional overrides:

```bash
OPENCODE_ZEN_MODEL=gpt-5.4-mini
OPENCODE_ZEN_BASE_URL=https://opencode.ai/zen/v1
```

## Run

```bash
uv run python -m evals.data_analysis.run
```

The runner prints plain progress logs and saves the same log data under `.eval_runs/data_analysis/<run-id>/run.log`. The default JSON report is written beside it as `.eval_runs/data_analysis/<run-id>/results.json`.

Defaults:

- Model: `gpt-5.4-mini`
- Base URL: `https://opencode.ai/zen/v1`
- Output: `.eval_runs/data_analysis/<run-id>/results.json`

You can also override with `--model`, `--base-url`, `--api-key`, or `--output`.

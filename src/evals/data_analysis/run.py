"""Run data-analysis evals comparing Deep Agents with and without Monty Python."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from dotenv import load_dotenv
from langchain.agents.middleware import TodoListMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from deepagents_monty import MontyCodeMiddleware
from evals.data_analysis.cases import (
    AGENT_DATASET_PATH,
    CSV_PATH,
    EVAL_CASES,
    SQLITE_PATH,
    EvalCase,
)
from evals.data_analysis.external_functions import TYPE_STUBS, make_read_csv

DEFAULT_MODEL = "gpt-5.4"
SYSTEM_PROMPT = """You are evaluating personal-finance data analysis.
Your transaction data is available in the virtual filesystem at /transactions.csv.
Answer the user's question exactly and concisely.
If a numeric answer is requested, return only the requested numeric value with no explanation.
"""


def _find_repo_root() -> Path:
    path = Path(__file__).resolve().parent
    for parent in [path, *path.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return path


REPO_ROOT = _find_repo_root()
RUNS_DIR = REPO_ROOT / ".eval_runs" / "data_analysis"
load_dotenv(REPO_ROOT / ".env")


class EvalLogger:
    """Write progress to stdout and a durable run log."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")

    def log(self, message: str = "") -> None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}" if message else ""
        print(line, flush=True)
        with self.path.open("a") as file:
            file.write(line + "\n")


def create_run_dir() -> Path:
    run_id = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S_UTC")
    path = RUNS_DIR / run_id
    counter = 1
    while path.exists():
        path = RUNS_DIR / f"{run_id}-{counter}"
        counter += 1
    path.mkdir(parents=True)
    return path


def expected_answer(case: EvalCase) -> str:
    """Compute a case's deterministic answer from the SQLite copy of the dataset."""
    with sqlite3.connect(SQLITE_PATH) as conn:
        row = conn.execute(case.sql).fetchone()
    if row is None:
        raise RuntimeError(f"No answer produced for case {case.id}")
    return case.answer_template.format(value=row[0])


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip("`$ ")


def grade_answer(actual: str, expected: str, tolerance: float) -> bool:
    actual_norm = normalize_answer(actual)
    expected_norm = normalize_answer(expected)
    actual_number = _first_number(actual_norm)
    expected_number = _first_number(expected_norm)
    if actual_number is not None and expected_number is not None:
        return abs(actual_number - expected_number) <= tolerance
    return actual_norm == expected_norm


def _first_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", value)
    if match is None:
        return None
    return float(match.group(0).replace(",", ""))


def extract_answer_content(content: Any) -> str:
    """Extract the assistant's final answer text from model message content.

    ChatOpenAI with the Responses API can return content as a list of content
    blocks rather than a plain string. The eval should grade the text answer,
    not the Python repr of those content blocks.
    """
    if isinstance(content, str):
        return content

    text = _extract_text_from_content_block(content, prefer_final_answer=True)
    if text is not None:
        return text

    if isinstance(content, Sequence) and not isinstance(content, str):
        final_answer_texts: list[str] = []
        fallback_texts: list[str] = []
        for block in content:
            final_text = _extract_text_from_content_block(block, prefer_final_answer=True)
            if final_text is not None:
                final_answer_texts.append(final_text)
                continue
            fallback_text = _extract_text_from_content_block(block, prefer_final_answer=False)
            if fallback_text is not None:
                fallback_texts.append(fallback_text)

        if final_answer_texts:
            return "\n".join(final_answer_texts)
        if fallback_texts:
            return "\n".join(fallback_texts)

    return str(content)


def _extract_text_from_content_block(block: Any, *, prefer_final_answer: bool) -> str | None:
    if isinstance(block, dict):
        phase = block.get("phase")
        block_type = block.get("type")
        text = block.get("text")
        if not isinstance(text, str):
            return None
        if prefer_final_answer:
            return text if phase == "final_answer" else None
        return text if block_type in {"text", "output_text"} or phase == "final_answer" else None

    text = getattr(block, "text", None)
    if not isinstance(text, str):
        return None
    if prefer_final_answer:
        return text if getattr(block, "phase", None) == "final_answer" else None
    return text


def make_model(
    *,
    model: str,
    base_url: str | None = None,
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low",
    name: str = "agent",
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        reasoning_effort=reasoning_effort,
        use_responses_api=True,
        output_version="responses/v1",
        max_retries=3,
        name=name,
    )


def configure_eval_harness_profile(model_name: str) -> None:
    register_harness_profile(
        f"openai:{model_name}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            excluded_middleware=frozenset({TodoListMiddleware}),
        ),
    )


def dataset_files() -> dict[str, Any]:
    return {AGENT_DATASET_PATH: create_file_data(CSV_PATH.read_text())}


def make_agent(
    *,
    model: ChatOpenAI,
    backend: StateBackend,
    with_monty: bool,
):
    middleware = []
    if with_monty:
        middleware.append(
            MontyCodeMiddleware(
                backend=backend,
                external_functions={"read_csv": make_read_csv(backend)},
                type_check_stubs=TYPE_STUBS,
            )
        )
    return create_deep_agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        backend=backend,
        middleware=middleware,
        subagents=(),
        checkpointer=MemorySaver(),
    )


async def seed_agent_filesystem(agent: Any, *, thread_id: str) -> None:
    await agent.aupdate_state(
        {"configurable": {"thread_id": thread_id}},
        {"files": dataset_files()},
    )


async def run_case(agent: Any, case: EvalCase, expected: str, *, thread_id: str) -> dict[str, Any]:
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": case.question}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        answer = extract_answer_content(result["messages"][-1].content)
        error = None
        passed = grade_answer(answer, expected, case.tolerance)
    except Exception as exc:  # noqa: BLE001 - record eval failures and continue.
        answer = ""
        error = f"{type(exc).__name__}: {exc}"
        passed = False
    return {
        "case": asdict(case),
        "expected": expected,
        "actual": answer,
        "passed": passed,
        "error": error,
    }


async def run_suite(*, model_name: str, base_url: str | None, logger: EvalLogger) -> dict[str, Any]:
    logger.log(f"Creating model {model_name} with base URL {base_url}")
    logger.log("Disabling default subagent and planning middleware")
    configure_eval_harness_profile(model_name)
    logger.log("Creating Deep Agents")
    agents = {
        "no_python": make_agent(
            model=make_model(
                model=model_name,
                base_url=base_url,
                name="basic-agent",
            ),
            backend=StateBackend(),
            with_monty=False,
        ),
        "monty": make_agent(
            model=make_model(
                model=model_name,
                base_url=base_url,
                name="monty-agent",
            ),
            backend=StateBackend(),
            with_monty=True,
        ),
    }
    logger.log(f"Running {len(EVAL_CASES)} cases across {len(agents)} agent variants")
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in agents}
    for case_index, case in enumerate(EVAL_CASES, start=1):
        expected = expected_answer(case)
        logger.log("")
        logger.log(f"[{case_index}/{len(EVAL_CASES)}] {case.id}")
        logger.log(f"Question: {case.question}")
        logger.log(f"Expected: {expected}")
        for agent_name, agent in agents.items():
            thread_id = f"data-analysis-evals-{agent_name}-{case.id}"
            logger.log(f"{agent_name}: seeding StateBackend filesystem in thread {thread_id}")
            await seed_agent_filesystem(agent, thread_id=thread_id)
            logger.log(f"{agent_name}: running")
            result = await run_case(agent, case, expected, thread_id=thread_id)
            results[agent_name].append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.log(f"{agent_name}: {status}")
            logger.log(f"{agent_name} actual: {result['actual'] or '<empty>'}")
            if result["error"]:
                logger.log(f"{agent_name} error: {result['error']}")
            elif not result["passed"]:
                logger.log(f"{agent_name} expected: {expected}")

    summary = {
        name: {
            "passed": sum(1 for result in agent_results if result["passed"]),
            "total": len(agent_results),
            "errors": sum(1 for result in agent_results if result["error"]),
        }
        for name, agent_results in results.items()
    }
    logger.log("")
    logger.log("Summary")
    for name, agent_summary in summary.items():
        logger.log(
            f"{name}: {agent_summary['passed']}/{agent_summary['total']} passed, "
            f"{agent_summary['errors']} errors"
        )
    return {
        "metadata": {
            "model": model_name,
            "base_url": base_url,
            "dataset_path": str(CSV_PATH),
            "agent_dataset_path": AGENT_DATASET_PATH,
        },
        "summary": summary,
        "results": results,
    }


def write_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output is None:
        print(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    run_dir = create_run_dir()
    logger = EvalLogger(run_dir / "run.log")
    output = args.output or run_dir / "results.json"
    logger.log(f"Eval run directory: {run_dir}")
    logger.log(f"Progress log: {logger.path}")
    logger.log(f"Results JSON: {output}")
    report = asyncio.run(
        run_suite(
            model_name=args.model,
            base_url=args.base_url,
            logger=logger,
        )
    )
    write_report(report, output)
    logger.log(f"Wrote results JSON: {output}")


if __name__ == "__main__":
    main()

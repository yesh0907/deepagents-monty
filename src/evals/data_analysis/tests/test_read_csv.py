"""Concrete coverage for the data-analysis CSV external function."""

from __future__ import annotations

from typing import Any, cast

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.protocol import BackendProtocol, FileData, ReadResult
from deepagents.backends.utils import create_file_data
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver

from deepagents_monty import MontyCodeMiddleware
from evals.data_analysis.cases import AGENT_DATASET_PATH, CSV_PATH, EVAL_CASES
from evals.data_analysis.external_functions import TYPE_STUBS, make_read_csv
from evals.data_analysis.run import expected_answer


class FailingSecondPageBackend:
    def read(self, path: str, offset: int = 0, limit: int = 2000) -> ReadResult:  # noqa: ARG002
        if offset == 0:
            return ReadResult(
                file_data=cast(
                    FileData,
                    {
                        "content": "Date,Amount\n"
                        + "\n".join("2024-01-01,1" for _ in range(limit - 1))
                    },
                )
            )
        return ReadResult(error="backend unavailable")


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel that accepts bind_tools (returns self)."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs) -> Runnable:  # noqa: ARG002
        return self


def _tool_result(messages: list[Any], tool_call_id: str) -> str:
    for msg in messages:
        if getattr(msg, "type", None) == "tool" and msg.tool_call_id == tool_call_id:
            return msg.content
    raise AssertionError(f"missing tool result: {tool_call_id}")


@pytest.fixture
def read_csv_agent():
    """A Deep Agent whose Monty runtime can parse transactions via read_csv."""
    backend = StateBackend()
    script: list[BaseMessage] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {
                        "code": (
                            "rows = read_csv('/transactions.csv')\n"
                            "total = 0.0\n"
                            "for row in rows:\n"
                            "    date = row['Date']\n"
                            "    amount = row['Amount']\n"
                            "    if row['Account Name'] == 'ORBIT CARD' and "
                            "date.startswith('2023-10') and amount > 0:\n"
                            "        total += amount\n"
                            "f'{round(total, 2):.2f}'"
                        )
                    },
                    "id": "read-csv",
                }
            ],
        ),
        AIMessage(content="120.47"),
    ]
    agent = create_deep_agent(
        model=ToolCapableFakeModel(responses=script),
        backend=backend,
        middleware=[
            MontyCodeMiddleware(
                backend=backend,
                external_functions={"read_csv": make_read_csv(backend)},
                type_check_stubs=TYPE_STUBS,
            )
        ],
        subagents=(),
        checkpointer=MemorySaver(),
    )
    return agent


async def test_read_csv_external_function_analyzes_seeded_transactions(read_csv_agent):
    await read_csv_agent.aupdate_state(
        {"configurable": {"thread_id": "read-csv-external"}},
        {"files": {AGENT_DATASET_PATH: create_file_data(CSV_PATH.read_text())}},
    )

    result = await read_csv_agent.ainvoke(
        {"messages": [{"role": "user", "content": EVAL_CASES[0].question}]},
        config={"configurable": {"thread_id": "read-csv-external"}},
    )

    expected = expected_answer(EVAL_CASES[0])
    assert expected == "120.47"
    assert f"return: '{expected}'" in _tool_result(result["messages"], "read-csv")


def test_read_csv_external_function_propagates_later_page_errors():
    read_csv = make_read_csv(cast(BackendProtocol, FailingSecondPageBackend()))

    with pytest.raises(OSError, match="line offset 2000"):
        read_csv("/transactions.csv")

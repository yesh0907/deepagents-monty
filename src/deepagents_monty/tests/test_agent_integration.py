"""End-to-end tests with a real Deep Agent and a scripted fake LLM.

Proves that ``python_repl`` and the stock filesystem tools share one
filesystem when wired through ``create_deep_agent`` with the same backend.
"""

from __future__ import annotations

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable

from deepagents_monty import MontyCodeMiddleware


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel that accepts bind_tools (returns self)."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs) -> Runnable:  # noqa: ARG002
        return self


def _collect_tool_results(messages) -> dict[str, str]:
    results: dict[str, str] = {}
    for msg in messages:
        if getattr(msg, "type", None) == "tool" or msg.__class__.__name__ == "ToolMessage":
            results[msg.tool_call_id] = msg.content
    return results


@pytest.fixture
def scripted_agent():
    """A Deep Agent with a scripted LLM that exercises cross-tool filesystem sharing."""
    shared_backend = StateBackend()
    script: list[BaseMessage] = [
        # Turn 1: write a file via Monty
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {
                        "code": (
                            "from pathlib import Path\n"
                            "Path('/monty_wrote.txt').write_text('hello from inside monty')\n"
                            "'done'"
                        )
                    },
                    "id": "c1",
                }
            ],
        ),
        # Turn 2: stock read_file reads what Monty just wrote
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"file_path": "/monty_wrote.txt"},
                    "id": "c2",
                }
            ],
        ),
        # Turn 3: stock write_file seeds another file
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {
                        "file_path": "/agent_wrote.txt",
                        "content": "hello from write_file tool",
                    },
                    "id": "c3",
                }
            ],
        ),
        # Turn 4: Monty reads what write_file wrote
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {
                        "code": ("from pathlib import Path\nPath('/agent_wrote.txt').read_text()")
                    },
                    "id": "c4",
                }
            ],
        ),
        AIMessage(content="All done."),
    ]
    fake_model = ToolCapableFakeModel(responses=script)

    agent = create_deep_agent(
        model=fake_model,
        middleware=[MontyCodeMiddleware(backend=shared_backend)],
        backend=shared_backend,
    )
    return agent


async def test_monty_writes_visible_to_read_file(scripted_agent):
    result = await scripted_agent.ainvoke({"messages": [{"role": "user", "content": "demo"}]})
    tool_results = _collect_tool_results(result["messages"])

    assert "return: 'done'" in tool_results["c1"]
    # read_file returns numbered-line output; check the content is there
    assert "hello from inside monty" in tool_results["c2"]


async def test_write_file_visible_to_monty(scripted_agent):
    result = await scripted_agent.ainvoke({"messages": [{"role": "user", "content": "demo"}]})
    tool_results = _collect_tool_results(result["messages"])

    assert "Updated file /agent_wrote.txt" in tool_results["c3"]
    assert "hello from write_file tool" in tool_results["c4"]


async def test_python_repl_state_persists_across_tool_calls():
    shared_backend = StateBackend()
    script: list[BaseMessage] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {"code": "counter = 41\ncounter"},
                    "id": "repl1",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {"code": "counter + 1"},
                    "id": "repl2",
                }
            ],
        ),
        AIMessage(content="All done."),
    ]
    fake_model = ToolCapableFakeModel(responses=script)
    agent = create_deep_agent(
        model=fake_model,
        middleware=[MontyCodeMiddleware(backend=shared_backend)],
        backend=shared_backend,
    )

    result = await agent.ainvoke({"messages": [{"role": "user", "content": "demo"}]})
    tool_results = _collect_tool_results(result["messages"])

    assert tool_results["repl1"] == "return: 41"
    assert tool_results["repl2"] == "return: 42"


async def test_python_repl_restart_resets_state():
    shared_backend = StateBackend()
    script: list[BaseMessage] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {"code": "counter = 41\ncounter"},
                    "id": "repl1",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "python_repl",
                    "args": {"code": "counter", "restart": True},
                    "id": "repl2",
                }
            ],
        ),
        AIMessage(content="All done."),
    ]
    fake_model = ToolCapableFakeModel(responses=script)
    agent = create_deep_agent(
        model=fake_model,
        middleware=[MontyCodeMiddleware(backend=shared_backend, type_check=False)],
        backend=shared_backend,
    )

    result = await agent.ainvoke({"messages": [{"role": "user", "content": "demo"}]})
    tool_results = _collect_tool_results(result["messages"])

    assert tool_results["repl1"] == "return: 41"
    assert tool_results["repl2"].startswith("RuntimeError:")
    assert "counter" in tool_results["repl2"]

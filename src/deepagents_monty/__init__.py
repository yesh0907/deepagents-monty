"""deepagents-monty: a Monty-backed code execution middleware for Deep Agents.

Usage::

    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend
    from deepagents_monty import MontyCodeMiddleware

    backend = StateBackend()  # shared
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        backend=backend,
        middleware=[MontyCodeMiddleware(backend=backend)],
    )
"""

from .bridge import DeepAgentBackendOS
from .middleware import (
    MONTY_SYSTEM_PROMPT,
    MontyCodeMiddleware,
    build_system_prompt,
    make_execute_python,
)

__version__ = "0.2.0"

__all__ = [
    "MONTY_SYSTEM_PROMPT",
    "DeepAgentBackendOS",
    "MontyCodeMiddleware",
    "build_system_prompt",
    "make_execute_python",
    "__version__",
]

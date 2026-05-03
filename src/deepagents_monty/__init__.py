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
from .middleware import MontyCodeMiddleware, make_execute_python

__version__ = "0.1.0"

__all__ = [
    "DeepAgentBackendOS",
    "MontyCodeMiddleware",
    "make_execute_python",
    "__version__",
]

"""COTA - Chain of Thought Agent Platform for Industrial-Grade Dialogue Systems

COTA can be used as a backend library in your Python applications.

Basic usage:
    ```python
    from cota import Agent, Application

    agent = Agent.load_from_path(path="/path/to/agent/config")
    async with Application(agent) as app:
        submission = await app.submit(
            user_id="user_123",
            session_id="session_456",
            text="Hello, how can you help me?",
        )
        result = await submission.wait()
        print(result["messages"])
    ```
"""

try:
    from importlib.metadata import version
    __version__ = version("cota")
except Exception:
    __version__ = "2.0.0"

# Core classes for library usage
from cota.agent import Agent
from cota.application import Application, Submission
from cota.message.message import Message
from cota.events import (
    Event,
    EventType,
    UserUtterEvent,
    BotUtterEvent,
    ToolResultEvent,
)

from cota.trace import build_trace

# Re-export commonly used items
__all__ = [
    "__version__",
    "Agent",
    "Application",
    "Submission",
    "Message",
    "Event",
    "build_trace",
    "EventType",
    "UserUtterEvent",
    "BotUtterEvent",
    "ToolResultEvent",
]

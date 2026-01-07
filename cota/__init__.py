"""COTA - Chain of Thought Agent Platform for Industrial-Grade Dialogue Systems

COTA can be used as a backend library in your Python applications.

Basic usage:
    ```python
    from cota import Agent, Message
    
    # Initialize agent from configuration directory
    agent = Agent.load_from_path(path="/path/to/agent/config")
    
    # Create a message
    message = Message(
        text="Hello, how can you help me?",
        sender="user",
        sender_id="user_123",
        session_id="session_456"
    )
    
    # Process the message
    processor = agent.create_processor()
    await processor.handle_message(message)
    ```
"""

__version__ = "1.1.1"  # same as pyproject.toml

# Core classes for library usage
from cota.agent import Agent
from cota.message.message import Message

# Re-export commonly used items
__all__ = [
    "__version__",
    "Agent",
    "Message",
]

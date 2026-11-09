"""COTA Event system — core event types for the agent loop.

All events produced during an agent loop are defined here.
Channel-layer messages (InboundMessage, OutboundMessage) live
in cota.channels.events — they are transport DTOs, not agent events.
"""

from cota.events.event import (
    Event,
    EventType,
    UserUtterEvent,
    BotUtterEvent,
    ToolResultEvent,
)

__all__ = [
    "Event",
    "EventType",
    "UserUtterEvent",
    "BotUtterEvent",
    "ToolResultEvent",
]

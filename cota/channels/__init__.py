"""Public Channel extension API; adapters are imported only when selected."""

from .base import BaseChannel
from .manager import ChannelManager
from .events import InboundMessage, OutboundMessage
from .queue import MessageBus
from .registry import ChannelRegistry
from .context import ChannelContext


def __getattr__(name):
    from importlib import import_module
    adapters = {
        'WebChannel': ('.web', 'WebChannel'),
        'FeishuChannel': ('.platforms.feishu', 'FeishuChannel'),
        'CmdlineChannel': ('.cmdline', 'CmdlineChannel'),
    }
    if name not in adapters:
        raise AttributeError(name)
    module, attribute = adapters[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value

__all__ = [
    "BaseChannel",
    "ChannelRegistry",
    "ChannelContext",
    "ChannelManager",
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
    "WebChannel",
    "FeishuChannel",
    "CmdlineChannel",
]

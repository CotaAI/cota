"""Channel 消息事件定义

定义 InboundMessage 和 OutboundMessage 作为所有 Channel 的统一消息格式。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class InboundMessage:
    """用户发来的消息 - 从 Channel 发送到 Agent"""

    channel: str  # web, feishu, cmdline
    sender_id: str  # 用户ID
    chat_id: str  # 会话ID
    content: str  # 文本内容
    timestamp: datetime = field(default_factory=datetime.now)
    media: List[str] = field(default_factory=list)  # 媒体URL
    metadata: Dict[str, Any] = field(default_factory=dict)  # 平台特定数据
    session_key_override: Optional[str] = None  # 可选的会话键覆盖

    message_id: Optional[str] = None

    mentioned: bool = False  # Trusted mention of this Bot, not a text search.
    sender_name: Optional[str] = None
    reply_to: Optional[str] = None
    conversation_type: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        from cota.files import validate_attachments
        self.attachments = validate_attachments(self.attachments)
        if type(self.mentioned) is not bool:
            raise ValueError('mentioned must be boolean')
        for key in ('sender_name', 'reply_to'):
            value = getattr(self, key)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 255):
                raise ValueError(f'{key} must be nonempty text of at most 255 characters')
        if self.conversation_type not in (None, 'direct', 'group'):
            raise ValueError('conversation_type must be direct or group')
        from cota.inputs import message_id
        self.message_id = message_id(self.message_id)

    @property
    def session_key(self) -> str:
        """唯一会话标识符"""
        if self.session_key_override:
            return self.session_key_override
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """发往用户的消息 - 从 Agent 发送到 Channel"""

    channel: str  # 目标 Channel
    chat_id: str  # 目标会话
    content: str  # 消息内容
    reply_to: Optional[str] = None  # 回复的消息ID（保留字段，暂未使用）
    media: List[str] = field(default_factory=list)  # 媒体URL
    metadata: Dict[str, Any] = field(default_factory=dict)  # 平台特定数据
    event_id: Optional[str] = None
    sequence: Optional[int] = None
    session_id: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        from cota.files import validate_attachments
        self.attachments = validate_attachments(self.attachments)

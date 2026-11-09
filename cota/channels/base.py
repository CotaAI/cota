"""BaseChannel - 所有 Channel 的抽象基类

所有 Channel 实现必须继承此类。
参考 NanoBot 的设计，提供统一的接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Text
from loguru import logger

from .events import InboundMessage, OutboundMessage
from .queue import MessageBus


class BaseChannel(ABC):
    """所有 Channel 必须继承的基类

    属性:
        name: Channel 标识符，如 'web', 'feishu', 'cmdline'
    """

    name: str = "base"  # Channel 标识符

    def __init__(self, config: Any, bus: MessageBus):
        """初始化 Channel

        Args:
            config: Channel 配置对象
            bus: 消息总线实例
        """
        self.config = config
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """启动 Channel，开始监听消息

        这应该是一个长期运行的异步任务：
        1. 连接到聊天平台
        2. 监听传入的消息
        3. 通过 _handle_message() 将消息转发到总线
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止 Channel 并清理资源"""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """通过此 Channel 发送消息

        Args:
            msg: 要发送的消息
        """
        pass

    async def send_response(self, recipient_id: Text, message: Dict[Text, Any]) -> None:
        """将 processor/legacy 格式的回复发送给客户端（兼容旧 API）

        将 {sender, sender_id, text, metadata} 转为 OutboundMessage 并调用 send()。

        Args:
            recipient_id: 会话/接收者 ID（如 session_id）
            message: 消息字典，通常包含 text、sender、metadata 等
        """
        text = message.get("text", "")
        out = OutboundMessage(
            channel=self.name,
            chat_id=str(recipient_id),
            content=text,
            metadata=message.get("metadata", {}),
        )
        await self.send(out)

    def is_allowed(self, sender_id: str) -> bool:
        """检查 sender_id 是否有权限

        白名单机制：
        - 空列表 → 拒绝所有
        - ["*"] → 允许所有
        - ["id1", "id2"] → 只允许指定ID

        Args:
            sender_id: 发送者ID

        Returns:
            bool: 是否允许
        """
        # 支持字典和对象两种配置方式
        if isinstance(self.config, dict):
            allow_list = self.config.get("allow_from", [])
        else:
            allow_list = getattr(self.config, "allow_from", [])

        if not allow_list:
            logger.warning(f"{self.name}: allow_from is empty — all access denied")
            return False
        if "*" in allow_list:
            return True
        sender_str = str(sender_id)
        return sender_str in allow_list or any(
            p in allow_list for p in sender_str.split("|") if p
        )

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_key: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """处理收到的消息并推送到消息总线

        此方法检查权限并将消息转发到总线。

        Args:
            sender_id: 发送者标识符
            chat_id: 聊天/频道标识符
            content: 消息文本内容
            media: 可选的媒体URL列表
            metadata: 可选的通道特定元数据
            session_key: 可选的会话键覆盖（如线程作用域会话）
            message_id: 平台消息 ID；省略时读取 metadata.message_id，否则自动生成
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                f"Access denied for sender {sender_id} on channel {self.name}. "
                f"Add them to allow_from list in config to grant access."
            )
            return

        if message_id is None:
            platform_id = (metadata or {}).get('message_id')
            message_id = str(platform_id) if platform_id is not None else None
        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
            message_id=message_id,
        )

        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        """检查 Channel 是否正在运行"""
        return self._running

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name}, running={self._running})>"

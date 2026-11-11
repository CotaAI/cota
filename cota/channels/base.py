"""BaseChannel - 所有 Channel 的抽象基类

内置和插件 Channel 共享此契约；Application 绑定接收入口，Manager 管理资源。
"""

import asyncio
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
    dialogue_modes = frozenset({'direct', 'group'})
    durable_delivery = False
    supports_attachments = False
    supports_streaming = False
    startup_timeout = 5.0

    def __init__(self, config: Any, bus: MessageBus):
        """初始化 Channel

        Args:
            config: Channel 配置对象
            bus: 消息总线实例
        """
        self.config = config
        self.bus = bus
        self._running = False
        self.context = None
        self._tasks = set()
        self._task_error = None

    def bind(self, context) -> None:
        """Bind host identity and Bot mode before validation/startup."""
        self.context = context
        self.name = context.name
        self.dialogue_mode = context.dialogue_mode
        if context.dialogue_mode not in self.dialogue_modes:
            raise ValueError(f'{self.name} supports dialogue.mode={", ".join(sorted(self.dialogue_modes))} only')

    def validate(self) -> None:
        """Validate adapter configuration without network or filesystem I/O."""

    def http_blueprint(self):
        """Optional Sanic Blueprint; Cota mounts it at /channels/{name}."""
        return None

    async def receive(self, message: InboundMessage):
        """Submit through Application; safe for webhook admission acknowledgments."""
        if self.context is None:
            raise RuntimeError('Channel is not bound to an Application')
        return await self.context.receive(message)

    def create_task(self, coroutine):
        """Supervise a listener; failure marks the adapter unhealthy."""
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self._task_error = type(error).__name__
            self._running = False
            logger.error('Channel {} background task failed ({})', self.name, self._task_error)

    async def cancel_tasks(self):
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @abstractmethod
    async def start(self) -> None:
        """启动 Channel，开始监听消息

        就绪后返回；监听循环使用 create_task()，由 Manager 监督和清理。
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

    async def send_stream(self, session_id: str, frame: dict) -> None:
        """Optional transient public-text preview; never a durable message."""

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
            metadata={**message.get("metadata", {}),
                      **({"request_id": message["request_id"]} if message.get("request_id") else {})},
            attachments=message.get('attachments', []),
            event_id=message.get('event_id'), session_id=message.get('session_id', str(recipient_id)),
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
        mentioned: bool = False,
        sender_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        conversation_type: Optional[str] = None,
    ) -> Any:
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
            mentioned=mentioned, sender_name=sender_name, reply_to=reply_to,
            conversation_type=conversation_type,
        )
        if self.context is not None:
            return await self.receive(msg)
        # Low-level standalone adapters (including Shell) use the bus directly.
        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        """检查 Channel 是否正在运行"""
        return self._running and self._task_error is None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name}, running={self._running})>"

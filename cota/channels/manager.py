"""ChannelManager - 统一管理所有 Channel

负责：
- 根据配置初始化启用的 Channel
- 启动/停止所有 Channel
- 路由出站消息到对应的 Channel
"""

import asyncio
from collections import deque
from typing import Any, Dict, Optional, List

from loguru import logger

from .base import BaseChannel
from .queue import MessageBus


class ChannelManager:
    """统一管理所有 Channel

    职责：
    - 初始化已启用的 Channel（Web、飞书、命令行）
    - 启动/停止 Channel
    - 路由出站消息
    """

    def __init__(self, config: Dict[str, Any], bus: MessageBus, store=None):
        """初始化 Channel 管理器

        Args:
            config: 包含所有 Channel 配置的字典
            bus: 消息总线实例
        """
        self.config = config
        self.bus = bus
        self.channels: Dict[str, BaseChannel] = {}
        self._dispatch_task: Optional[asyncio.Task] = None
        self._on_message_callback = None  # 消息处理回调
        self._start_tasks = {}
        self.startup_failures = {}
        self._routes = {}
        self._route_tasks = {}
        self._outbound_pending = 0
        limits = config.get("channel_limits", {})
        self._max_outbound = int(limits.get("max_outbound", 512))
        self._max_route_pending = int(limits.get("max_route_pending", 64))
        self._send_timeout = float(limits.get("send_timeout", 10.0))
        self._lifecycle_timeout = float(limits.get("lifecycle_timeout", 5.0))
        if min(self._max_outbound, self._max_route_pending, self._send_timeout, self._lifecycle_timeout) <= 0:
            raise ValueError("Channel limits must be positive")

        self._init_channels()
        self.delivery = None
        if store is not None:
            from .delivery import DeliveryDispatcher
            self.delivery = DeliveryDispatcher(store, self.channels,
                concurrency=limits.get('delivery_concurrency', 8),
                max_attempts=limits.get('delivery_max_attempts', 8),
                poll_interval=limits.get('delivery_poll_interval', .25),
                retry_delay=limits.get('delivery_retry_delay', 1),
                max_retry_delay=limits.get('delivery_max_retry_delay', 300),
                send_timeout=self._send_timeout,
                shutdown_timeout=limits.get('delivery_shutdown_timeout', self._lifecycle_timeout))

    def _init_channels(self) -> None:
        """根据配置初始化所有启用的 Channel"""
        channel_configs = self.config.get("channels", {})
        supported = {'web', 'feishu', 'cmdline'}
        unsupported = set(channel_configs) - supported
        if unsupported:
            raise ValueError(
                f'Unsupported channel(s): {", ".join(sorted(unsupported))}. '
                'Supported channels: web, feishu, cmdline.'
            )

        # Web Channel (浏览器/小程序访问)
        web_config = channel_configs.get("web", {})
        if web_config.get("enabled", False):
            from .web import WebChannel
            self.channels["web"] = WebChannel(web_config, self.bus)
            logger.info("Web channel enabled")

        # Feishu (飞书)
        feishu_config = channel_configs.get("feishu", {})
        if feishu_config.get("enabled", False):
            try:
                from .platforms.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(feishu_config, self.bus)
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning(f"Feishu channel not available: {e}")

        # Cmdline (命令行)
        cmdline_config = channel_configs.get("cmdline", {})
        if cmdline_config.get("enabled", False):
            from .cmdline import CmdlineChannel
            self.channels["cmdline"] = CmdlineChannel(cmdline_config, self.bus)
            logger.info("Cmdline channel enabled")

        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        """验证权限配置"""
        # 不需要验证 allow_from 的 Channel 类型
        optional_channels = {"web", "cmdline"}

        for name, ch in self.channels.items():
            # 这些 Channel 可以没有 allow_from 配置
            if name in optional_channels:
                continue

            # 支持字典和对象两种配置方式
            if isinstance(ch.config, dict):
                allow_from = ch.config.get("allow_from", None)
            else:
                allow_from = getattr(ch.config, "allow_from", None)

            if allow_from is None or allow_from == []:
                raise SystemExit(
                    f'Error: "{name}" has empty allow_from (denies all). '
                    f'Set ["*"] to allow everyone, or add specific user IDs.'
                )

    def set_message_handler(self, handler) -> None:
        """设置消息处理回调（用于 CmdlineChannel）"""
        self._on_message_callback = handler
        # 如果 cmdline 已初始化，更新回调
        if "cmdline" in self.channels:
            self.channels["cmdline"].set_message_handler(handler)

    def _observe_start(self, name, task):
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.startup_failures[name] = str(error)
                logger.error(f"Channel {name} failed: {error}")

    async def start_all(self) -> None:
        """Await adapter readiness; supervise long-running platform listeners.

        Web and cmdline start() return once ready. Existing platform start()
        methods own a listener loop, so their tasks remain managed until stop.
        """
        if self._dispatch_task is not None:
            return
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        try:
            for name, channel in self.channels.items():
                task = asyncio.create_task(channel.start())
                self._start_tasks[name] = task
                task.add_done_callback(lambda done, name=name: self._observe_start(name, done))
            ready = [task for name, task in self._start_tasks.items() if name in {"web", "cmdline"} or getattr(self.channels[name], "startup_ready", False)]
            if ready:
                timeout = max([self._lifecycle_timeout] + [getattr(channel, 'startup_timeout', 0)
                                                          for channel in self.channels.values()])
                done, pending = await asyncio.wait(ready, timeout=timeout)
                if pending:
                    raise TimeoutError("Channel startup timed out")
                for task in done:
                    task.result()
            # Surface immediate platform startup errors without awaiting listener exit.
            await asyncio.sleep(0)
            for task in self._start_tasks.values():
                if task.done():
                    task.result()
            if self.delivery:
                self.delivery.channels = self.channels
                await self.delivery.start()
        except BaseException:
            await self.stop_all()
            raise

    async def stop_all(self) -> None:
        if self.delivery:
            # Execution has stopped producing replies; drain sends before
            # closing adapters. Unsent rows remain in Store for next startup.
            await self.delivery.stop()
        tasks = list(self._start_tasks.values()) + list(self._route_tasks.values())
        if self._dispatch_task:
            tasks.append(self._dispatch_task)
        for task in tasks:
            task.cancel()
        # Stop adapters concurrently so one unhealthy adapter cannot serialize shutdown.
        stops = [asyncio.create_task(channel.stop()) for channel in self.channels.values()]
        all_tasks = tasks + stops
        if all_tasks:
            done, pending = await asyncio.wait(all_tasks, timeout=self._lifecycle_timeout)
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        logger.error(f"Error stopping channel: {error}")
            for task in pending:
                task.cancel()
                task.add_done_callback(self._observe_shutdown)
            if pending:
                logger.error(f"{len(pending)} channel tasks exceeded shutdown timeout")
        self._start_tasks.clear()
        self._dispatch_task = None
        self._routes.clear()

    @staticmethod
    def _observe_shutdown(task):
        if not task.cancelled() and task.exception() is not None:
            logger.error(f"Channel shutdown task failed: {task.exception()}")

    async def _send_route(self, key, channel, queue):
        try:
            while queue:
                message = queue.popleft()
                try:
                    await asyncio.wait_for(channel.send(message), self._send_timeout)
                except Exception as error:
                    logger.error(f"Error sending to {key}: {error}")
                finally:
                    self._outbound_pending -= 1
        finally:
            self._outbound_pending -= len(queue)
            self._routes.pop(key, None)
            self._route_tasks.pop(key, None)

    async def _dispatch_outbound(self) -> None:
        """Bounded per-target send queues preserve order without cross-target waits.

        On overload delivery is reported and dropped; durable Web messages can
        still be recovered from history. A stalled target never blocks routing.
        """
        while True:
            msg = await self.bus.consume_outbound()
            if msg is None:
                return
            if msg.metadata.get("_progress"):
                tool_hint = msg.metadata.get("_tool_hint")
                settings = self.config.get("channels", {})
                if tool_hint and not settings.get("send_tool_hints", True):
                    continue
                if not tool_hint and not settings.get("send_progress", True):
                    continue
            channel = self.channels.get(msg.channel)
            if channel is None:
                logger.warning(f"Unknown channel: {msg.channel}")
                continue
            key = (msg.channel, msg.chat_id)
            queue = self._routes.get(key)
            if self._outbound_pending >= self._max_outbound or (queue is not None and len(queue) >= self._max_route_pending):
                logger.error(f"Outbound queue full; delivery dropped for {key}")
                continue
            if queue is None:
                queue = deque()
                self._routes[key] = queue
                self._route_tasks[key] = asyncio.create_task(self._send_route(key, channel, queue))
            queue.append(msg)
            self._outbound_pending += 1

    def get_channel(self, name: str) -> Optional[BaseChannel]:
        """根据名称获取 Channel"""
        return self.channels.get(name)

    @property
    def enabled_channels(self) -> List[str]:
        """获取已启用的 Channel 列表"""
        return list(self.channels.keys())

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有 Channel 的状态"""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running,
                "error": self.startup_failures.get(name)
            }
            for name, channel in self.channels.items()
        }

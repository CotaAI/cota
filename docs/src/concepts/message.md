# Message：输入、传输和持久化标识

Cota 区分三种对象：SDK 的 `Message`、Channel 的 `InboundMessage` / `OutboundMessage`，以及 Store 中的对话和执行事件。它们在边界上转换，不应混用身份或投递状态。

## SDK 输入

```python
from cota.message.message import Message

message = Message(
    sender="user", sender_id="alice", receiver="bot",
    session_id="support-001", message_id="input-001",
    text="请帮我查询订单", metadata={"source": "my-app"},
)
await processor.handle_message(message)
```

`sender` 默认 `user`，未提供 `sender_id` 时使用默认身份；未提供 `session_id` 和 `message_id` 时生成标识。`text` 会去掉首尾空白。`receiver` 默认为空，只有显式设为 `bot` 才触发这条 SDK 路径的 Bot 执行。

服务接入应由认证层提供稳定用户身份。需要重试的客户端应复用原 `message_id`；每次生成新标识会被视为新输入。同一标识重复提交相同输入可返回既有状态，修改内容或身份则冲突。

## Channel 消息

`InboundMessage` 必填 `channel`、`sender_id`、`chat_id`、`content`。它还携带媒体、平台 metadata、`message_id`，以及群聊的 `mentioned`、`sender_name`、`reply_to`、`conversation_type`。

默认 `session_key` 为 `channel:chat_id`；可信应用可通过 `session_key_override` 绑定已有会话。Bot mention 是适配器识别的结构化信号，不由正文字符串猜测。群消息应交给 `Application.submit_message()`。

`OutboundMessage` 包含目标 channel/chat、正文、媒体和 metadata，以及可选的持久化 `event_id`、`sequence`、`session_id`。这些事件标识用于重放、去重和投递关联。

## Web 身份与回复

WebSocket 首帧 `resume` 认证并绑定用户和会话，后续 `send` 不能自行改写 `user_id`、`sender_id` 或 `session_id`。HTTP 与 WebSocket 使用同一授权服务。

`bot_utter` 持久化后才向传输层发布。收到 receipt、进入发送队列、平台接受和用户看到消息是不同阶段；具体保证见 [可靠投递](../deployment/delivery.md)。

实现入口：`cota/message/message.py`、`cota/channels/events.py`、`cota/inputs.py`、`cota/processor.py`。

相关文档：[Channel](channel.md) · [DST](dst.md) · [应用 API](../deployment/api.md) · [群聊](../deployment/group.md)

# 自定义 Channel 接入

需要收发附件时，适配器使用统一 attachments 引用并声明 `supports_attachments = True`，从绑定的 `channel.files` 读取当前会话副本，再调用平台上传/发送 API。未声明支持时不会丢弃附件后当作文字成功发送。详见 [会话附件](../concepts/attachments.md)。

Channel 负责平台身份、会话、输入协议与回复投递。Cota 负责排队、持久化、Bot 执行和失败投递恢复。平台接入可以作为独立 Python 包交付，无需修改 Cota 内置 Channel 清单。

如果已经有适配包，按下文安装、配置并启动即可。如果要接入公司 IM（例如 SeaTalk）或新的业务平台，先参考仓库中的独立 Webhook/REST 示例实现适配器，再声明 entry point 并打包；接入方使用同一套安装流程。

## 安装与启用

插件包通过 `pyproject.toml` 声明工厂：

```toml
[project]
name = "cota-channel-example"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["cota>=2.0.0"]

[project.entry-points."cota.channels"]
example_im = "cota_channel_example:ExampleIMChannel"
```

在**运行 Cota 的同一个 Python 环境**中安装插件。仓库包含可执行的[通用 Webhook/REST 示例](https://github.com/CotaAI/cota/tree/main/examples/channel-plugin)，从仓库根目录安装：

```bash
uv pip install ./examples/channel-plugin
```

真实外部插件也可从包索引或本地 wheel 安装，例如 `uv pip install /path/to/your_channel.whl`。安装只增加可发现的类型，不会自动启用、监听端口或连接平台；每个 Application 持有自己的 registry，只有选中的已启用类型才加载工厂。类型重名或与内置类型冲突会报错，应给包选择独立名称。

将配置合并进 Bot 的 `endpoints.yml`：

```yaml
channels:
  office_im:
    enabled: true
    type: example_im
    app_id: app-one
    webhook_secret: replace-with-random-secret
    api_base: https://gateway.example/v1
    api_token: replace-with-api-token
```

配置完成后启动 Bot：

```bash
cota run --config ./my-bot --host 127.0.0.1 --port 5005
```

上述示例的回调为 `POST http://127.0.0.1:5005/channels/office_im/webhook`，出站请求由适配器发送到配置的 `api_base`。真实平台需要填写它能访问的 HTTPS 回调地址，监听与反向代理配置见 [部署指南](../deployment/guide.md)。插件自行实现平台要求的路径和协议；通用示例不是 SeaTalk 的原生适配器。

Cota 在服务启动时发现已安装的 entry points。安装新插件或修改 Channel 配置后需重启服务；无需另写注册脚本，也无需为每条输入创建 Agent 或运行服务。未配置其他入口时，只启用这个插件即可，无需同时启用 `web`。

映射键 `office_im` 是运行实例名；同一类型可以配置多个实例。省略 `type` 时使用实例名查找类型；`enabled` 缺省为 false，必须是布尔值。实例名和类型名由小写字母开头，包含小写字母、数字及分隔用的 `_` / `-`，最多 64 字符。未知的已启用类型启动失败；未启用类型可先保留配置而不安装依赖。内置 Web 必须使用 `web` 类型和 `web` 实例，不能别名或覆盖。

也可绕过 entry point 指定 import 工厂，此时仍须安装模块，并删除 `type`：

```yaml
channels:
  office_im:
    enabled: true
    factory: "cota_channel_example:ExampleIMChannel"
    app_id: app-one
    webhook_secret: replace-with-random-secret
    api_base: https://gateway.example/v1
    api_token: replace-with-api-token
```

`type` 与 `factory` 互斥。插件是可信 Python 代码；只安装可信发布方的包，密钥由部署方注入配置，不提交版本库、不写入日志。

## 适配器契约

工厂是同步 callable，接收 `(settings, bus)`，返回 `BaseChannel`。可直接使用继承 `BaseChannel` 的类作为工厂。Cota 绑定实例名和 `ChannelContext` 后调用 `validate()`，然后才开始运行。

| 方法或属性 | 责任 |
| --- | --- |
| `__init__(settings, bus)` | 只保存配置与本地状态，不连接网络 |
| `validate()` | 同步验证必填字段、类型与协议约束，不做 I/O |
| `context.dialogue_mode` | 当前 Bot 的 `direct` 或 `group`，不能由未验证请求自行切换 |
| `http_blueprint()` | 可选同步返回 Sanic Blueprint；名称包含 `self.name`，框架挂到 `/channels/{实例名}` |
| `start()` / `stop()` | 就绪后返回；共享连接在此创建和关闭，停止可重复调用 |
| `dialogue_modes` | 支持的模式集合，默认 direct/group；只支持单聊可声明 `frozenset({'direct'})` |
| `create_task(coroutine)` | 注册长连接监听等后台工作；失败由管理器观察，关闭时取消 |
| `receive(InboundMessage)` | 使用 Application 的持久化接收流程，返回 Submission |
| `durable_delivery` / `delivery_scope` | 需要可靠出站时设为 true，并提供稳定的平台应用身份，例如 app_id |
| `send(OutboundMessage)` | 只发送该已提交回复；失败必须抛异常，让 Cota 安排重试 |

Webhook Blueprint 与内置 Web Channel 独立，无需启用 `channels.web`，也不应自行启动第二个 HTTP server。`cota run` 的 host/port 控制统一 listener。新增平台不需要添加核心 HTTP 路由。SDK 可向 `Application(..., channel_registry=registry)` 或 `create_app(..., channel_registry=registry)` 传入预先 `register(name, factory)` 的 registry。

监听器可能在自己的 `start()` 返回后立即收到消息。此时 `receive()` 会等待整个 Application 就绪；启动失败或服务关闭时拒绝接收，不能返回成功 ACK。`start()` 本身只等待连接就绪，不应等待某条业务输入接收完成，否则会阻塞整体启动。

## 可信输入与接收确认

插件必须在调用 `receive()` 前完成平台验签、应用身份检查、用户授权与群成员判断。用户 ID、会话 ID、@Bot、显示名和回复目标都来自已验证的平台事件；不要从用户文本猜测 @Bot，也不要接受外部请求指定内部 session key。使用实例名与 app_id 隔离用户、会话身份，避免两个租户的同名 room 共用状态。

`InboundMessage` 应提供稳定的平台 `message_id`；重试保留 ID 和原内容。群聊还应传入 `conversation_type='group'`、可信 `mentioned`，可选 `sender_name` 与 `reply_to`。Cota 使用这些字段判断是否参与和构建上下文；静默收录也可能返回 `recorded` receipt。一个 Bot 使用一个 `dialogue.mode`，框架不会自动把私聊与群聊混成一种会话。

示例协议先验证原始请求体的 HMAC-SHA256，`X-Signature` 为十六进制摘要；JSON 包含 `user_id/chat_id/text/message_id`。签名密钥只属于可信网关，网关负责真实平台认证、授权与群身份。示例不是 SeaTalk 接入实现，真实平台的签名、挑战应答、重放窗口、token 与附件协议需要适配器自行补齐。

```python
submission = await self.receive(inbound)
receipt = await submission.receipt()
# 现在返回平台 ACK；不要等待 submission.wait() 才确认接收。
```

只有持久化接收成功才返回成功 ACK；`receipt` 表示接收/执行状态，不保证回复已到平台。示例成功返回 `202`，包含 `message_id`、`duplicate` 和 `receipt`；容量不足或服务正在关闭返回 `503` 和 `Retry-After`，要求发送方用同 ID 重试。ID 与内容冲突返回 `409`，签名失败 `401`，格式错误 `400`。使用 SQL Store 才能跨进程重启保留这些事实。

## 可靠回复与调试

示例在 `start()` 创建一个 HTTPX AsyncClient，POST 到 `{api_base}/messages`，以 Bearer token 认证，并携带 `Idempotency-Key: <event_id>`。Cota 的持久化出站记录保存稳定的 `event_id`；网关/平台应以该 ID 去重。网络超时可能发生在平台已经接收之后，因此投递是至少一次，不能承诺远端恰好一次。插件不要吞异常、重复执行输入或自行叠加重试循环。

同一 Bot 的执行数据库使用一个 Application 执行进程。使用 `cota run --config ./my-bot --debug` 开启同一服务的 [Debug 页面](../deployment/debug.md)，查看会话和投递状态；不要另起执行循环操作同一数据库。出站重试只重发已有回复，不重跑模型或工具。业务效果、平台限流、密钥轮换与连接恢复策略由适配器和部署方验证。

仓库测试覆盖验签、direct/group 身份隔离、先持久化后 ACK、重复输入、忙时重试、REST 错误及共享连接关闭，不访问真实平台：

```bash
.venv/bin/pytest -q tests/channels/test_example_plugin.py tests/channels/test_registry.py
```

相关文档：[Channel 边界](../concepts/channel.md) · [Endpoints 配置](../configuration/endpoints.md) · [Application](../deployment/application.md) · [群聊](../deployment/group.md) · [可靠投递](../deployment/delivery.md)

## 可选的实时预览

插件默认只接收完整、已提交的回复。支持实时编辑消息的 Channel 可以声明 `supports_streaming = True` 并实现 `async send_stream(session_id, frame)`。Application 从已经接收的输入绑定可信会话路由，Processor 把该回调独立于正式回复与 outbox 传给 runtime。

frame 包含 `session_id`、`run_id`、`request_id`、`phase`（start/delta/end/error），delta 另有 `text`。该接口只接收公开文字；必须快速返回并使用有界缓冲，不能把片段写入持久化投递队列。最终已提交回复仍通过 `send()` 发送，request_id 用于替换预览。end 不等于持久化成功；不支持预览的平台保留完整回复投递即可。接口示例和重连语义见 [Web 接入协议](../deployment/api.md#实时文字预览)。

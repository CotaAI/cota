# Channel：连接用户与 Bot

Channel 把平台输入转换成 `InboundMessage`，把已经提交的回复送回对应会话。Bot 的业务配置和执行循环可以复用，平台身份、会话授权和投递方式由 Channel / 应用层处理。

## 内置入口与外部插件

| 入口 | 用途与约束 |
| --- | --- |
| `cmdline` | 本地 shell 交互与开发调试 |
| `web` | 同一 HTTP listener 上的授权 HTTP API 与 WebSocket 聊天 |
| `feishu` | 飞书长连接接入，需安装可选依赖并配置应用身份与允许用户 |

其他平台通过独立 Python 包的 `cota.channels` entry point 接入，也可指定 `module:callable` 工厂。安装不会自动启用插件；配置中的实例名用于路由，`type` 选择实现，省略时与实例名相同。已禁用的类型不加载适配器代码，已启用但未安装的类型会报错。同一类型可配置多个实例，内置 `web` 保留固定实例名。开发契约与通用 Webhook/REST 示例见 [Channel 插件开发](../development/channel-plugins.md)。

Web transport 目前只实现 `websocket`；`auto` 也选择 WebSocket。不支持旧 SSE、Socket.IO 或每个 Web Channel 单独监听端口的配置。MCP 远程连接使用 SSE 是另一套协议，不代表 Web Channel 支持 SSE。

内置 Web app 是可选界面；可用自己的网页、客户端或应用调用服务 API。应用启动和 HTTP/WS listener 由 `create_app()` / `cota run` 管理。

## 生命周期与调度

Application 持有 Agent、ChannelRunner 和 ChannelManager。Runner 对输入排队并调度执行，Manager 通过每个应用独立的 ChannelRegistry 创建已启用的适配器、绑定可信上下文并管理生命周期和出站路由。适配器构造与配置验证不连接平台；start 就绪后返回，后台监听由管理器监督。一个慢会话不应阻塞其他会话，同一会话仍需保持执行与回复顺序。

平台适配器完成认证和授权后，调用 `Channel.receive()` 将输入交给 Application；成功 ACK 表示输入已经持久化，不需要等待模型执行结束。忙时返回可重试结果，平台以相同 message_id 和内容重试。群聊的 @Bot、成员身份和回复目标必须来自可信平台事件。插件的 HTTP 回调挂在 `/channels/{实例名}`，使用统一 listener，无需启用内置 Web。

出站可以由持久化 DeliveryDispatcher 从 Store 读取，避免平台发送失败导致重复模型或工具执行。适配器声明稳定的平台应用身份，并以已提交回复的 event_id 请求平台去重；投递是至少一次，远端是否去重取决于平台。停止服务时先停止产生新回复，再处理投递关闭；未发出的持久化记录可在下次启动恢复。跨进程恢复需要 SQL Store；同一 Bot 数据库由一个 Application 执行进程负责。

## 配置位置

```yaml
channels:
  web:
    enabled: true
    transport: websocket
```

CLI 从 `agent.yml` 和 `endpoints.yml` 合并 `channels`，后者覆盖同名配置项。推荐把平台接入字段放在 `endpoints.yml`。服务监听 host/port 使用 `cota run` 参数，不放进 `channels.web`。

Web 默认可用 GuestAccess 提供访客会话；自有账号系统或群聊需配置可信认证与会话成员检查。飞书的 `allow_from: []` 表示拒绝所有人，`["*"]` 表示允许全部用户；标准 ChannelManager 会拒绝启动缺省或空 allow_from 的已启用飞书 Channel。详细字段见 [Endpoints 配置](../configuration/endpoints.md)。

实现入口：`cota/channels/runner.py`、`cota/channels/manager.py`、`cota/channels/web/transport.py`、`cota/server.py`。

相关文档：[Message](message.md) · [插件开发](../development/channel-plugins.md) · [Application](../deployment/application.md) · [Web app](../deployment/chat-app.md) · [飞书](../deployment/feishu.md) · [可靠投递](../deployment/delivery.md)

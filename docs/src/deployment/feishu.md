# 飞书接入

支持飞书企业自建应用的单聊和群聊文本，由 agent.yml 的 dialogue.mode 选择。以下介绍默认单聊；群聊配置和边界见 [公共群聊基础](group.md)。长连接、心跳、重连和事件解析复用官方 lark-oapi SDK；Cota 负责身份映射、接收去重、Bot 执行与文本回复。

## 安装与配置

```bash
uv pip install 'cota[feishu]'
```

从当前源码开发时使用 `uv pip install -e '.[feishu]'`。源码环境还需准备 Node 并运行 `npm ci --prefix cota/runtime/pi`；带 runtime 的平台 wheel 则已包含 Node/Pi，见 [安装说明](../installation/install.md)。

agent.yml 中选择通道：

```yaml
channels:
  web:
    enabled: false
  feishu:
    enabled: true
    allow_from: ['*']
```

在同一 Bot 的 endpoints.yml 中增加部署凭据，不需要 export：

```yaml
channels:
  feishu:
    app_id: '填写飞书应用 App ID'
    app_secret: '填写飞书应用 App Secret'
```

endpoints.yml 的 channels 按通道、按字段覆盖 agent.yml 的默认设置。`allow_from: []` 拒绝所有人；填写 open_id 列表只允许指定用户；`['*']` 允许应用可用范围内的用户。分享 Bot 文件夹前删除自己的密钥。

飞书开放平台中开启应用的机器人能力，订阅 `im.message.receive_v1`，选择长连接接收事件，开通该事件要求的单聊消息读取权限，以及以机器人身份发送消息的权限；发布应用并把测试用户加入应用可用范围。配置细节以 [官方长连接文档](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-) 与 [接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive) 为准。

```bash
cota run --config ./bots/weather --host 127.0.0.1 --port 5005
```

Bot 的 LLM、Store 等仍按原有 endpoints.yml 配置。单独启用飞书时，HTTP 仅保留健康检查和版本接口，不暴露 Web 聊天页面或访客入口。需要同时开放 Web 时明确设置 channels.web.enabled 为 true。

无需提供公网回调地址。服务需要能访问飞书开放平台与长连接服务。当前 SDK 工作进程适配面向 macOS/Linux。启动会等待 SDK 连接就绪；失败会终止启动，不把未连接的飞书标记为健康。`/api/health` 返回各通道状态。

## 消息链路

```text
飞书官方 SDK 收到单聊文本
  → Cota 校验应用、用户类型、单聊类型、allow_from
  → InboundMessage → ChannelRunner → Application → Processor → Pi
  → Store 同时保存 bot_utter 与投递记录 → 持久化投递器 → 飞书发送消息 API
```

身份范围：

```text
user_id    = feishu:{app_id}:{tenant_key}:{open_id}
session_id = feishu:{app_id}:{tenant_key}:p2p:{chat_id}
message_id = 飞书原始 message_id
```

原始 chat_id 仅作为飞书回复目标，带范围的 session_id 用于 Cota 历史和执行顺序。默认 direct 模式忽略群聊；group 模式接收群文本并按响应规则执行。机器人消息、图片/文件等不进入模型。单聊中不同用户不共享历史或用户记忆；群聊共享群历史，但不加载成员私有记忆；Web 与飞书不会自动关联为同一用户。

## 投递和验证范围

同一事件重复到达由 Store/Runner 去重，不重复执行模型。SDK 确认的是内存队列接收，尚未持久化的输入仍存在进程崩溃丢失窗口。服务不是持久化消息队列。

回复使用 chat_id 接收类型，带基于事件 ID 的稳定 UUID；发送中的短暂网络错误及部分 HTTP 错误会有限重试。持久化投递器会继续退避重试，SQLStore 在重启后自动恢复待投递回复，不重新执行模型或工具。达到上限保留 failed 状态，可人工重试；同一目标的后续回复等待前一条成功。执行 completed 不等于飞书投递成功，详细语义见 [回复投递与恢复](delivery.md)。消息内容仍受飞书文本 API 大小等约束。见 [官方发送消息 API](https://open.feishu.cn/document/server-docs/im-v1/message/create)。

测试覆盖真实 SDK 模型解析、工作进程握手、双用户隔离、会话内顺序、重复事件与保存后发送；测试中的飞书网络和模型响应被替换。上线前仍需使用自己的应用验证权限、事件订阅、接收与回复。

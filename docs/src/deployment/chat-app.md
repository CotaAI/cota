# 可选聊天应用

Cota 的配套聊天应用为没有现成前端的 Bot 提供访问入口。它是应用层模块，位于 `cota/webapp/`，与 `cota/channels/` 并列；Web Channel、Application、DST、Store 和 Pi 不依赖它。

## 启动与分享

```bash
cota run --config ./bots/weather --chat-app --host 127.0.0.1 --port 5005
```

打开 `http://127.0.0.1:5005/chat/`，填写昵称创建访客身份，再创建对话。不加 `--chat-app` 时只启动通道 API，不挂载聊天页面或应用管理接口，也不创建应用数据库。对外分享时使用自己的域名和 HTTPS 部署；将页面链接发给别人即可，各人的单聊互相隔离。

同一个服务使用 agent.yml 中的一种模式：

```yaml
dialogue:
  mode: group
  response: passive
  prompt: |
    你是群聊中的助手。区分成员的需求，回答简洁。
channels:
  web:
    enabled: true
```

group 下可以创建群聊、生成邀请链接并邀请他人加入同一个会话。只有群主可以生成邀请和移除成员；其他成员可以退出。普通发言会保存并同步给成员，勾选 @Bot 才触发被动 Bot；引用消息本身不会触发。proactive 模式的参与判断沿用 [公共群聊基础](group.md)。单聊不提供邀请或成员操作。模式不由前端逐会话指定。

应用提供会话列表、最近消息预览、最后活跃时间、未读数、已读游标、消息分页、发言者显示、发送状态、引用、@Bot 和断线恢复。所有消息通过 `/ws` 和 `/api/conversations/{id}/messages` 读写，不直接访问 DST、Store 或调试接口。

## 身份、权限与邀请

第一版是**访客身份**，不是账号系统。凭据保存在当前浏览器，有效期 30 天；清理浏览器数据、退出身份、凭据过期后，不能用同一个昵称找回原身份。需要跨设备登录或账号恢复时，接入自己的身份系统和界面，使用 [Web 接入契约](api.md)。昵称仅用于展示，权限绑定服务端签发的 user_id。

群邀请是持有链接即可使用的授权入口，有效期七天；同一群再次生成邀请会作废旧链接。邀请放在链接 fragment（`#invite=...`）中，页面读取后从地址栏移除；数据库只保存摘要。移除成员或成员退出时也会作废原邀请，避免被移除者用旧链接重新加入。每群最多 256 名成员。加入者可查看完整群历史，邀请应发给允许查看这些历史的人。

身份与成员权限在历史查询、发送、状态查询、建立订阅，以及每个排队/实时帧投递前检查。失去权限的连接不能继续获取后续消息，下一次发送或投递时关闭；已下载到终端的历史无法远程收回。正在执行的 Bot 请求不会因发起者退出而取消，结果仍归属原群并只向有权成员投递。

## 存储边界

```text
浏览器 → 配套应用管理接口 → ChatRegistry（会话、成员、邀请）
      → Web Channel      → Application → DST / Store / Pi
```

Bot 目录 `.cota/` 下：

| 文件 | 内容 |
| --- | --- |
| `chat.sqlite3` | 访客昵称、会话标题、成员关系、邀请摘要与有效期、每成员已读游标 |
| `chat.key` | 本部署的访客凭据签名密钥 |

聊天正文、工具执行和模型上下文仍使用 endpoints.yml 配置的 Cota Store；配套应用不复制这些内容。正式保留历史需要持久化 Store，MemoryStore 仅用于测试。恢复部署时需要一起保留应用数据库、签名密钥和 Cota Store。`.cota/` 不提交到仓库，也不放入分享的 Bot 包。

registry.py 不导入 Cota Store、DST 或 Runtime；access.py 实现 Web 公开的 authenticate/authorize 契约；app.py 组合公开 server factory 和自己的 HTTP 路由；static/ 只使用公开 API 与 CotaClient。不新增核心 Event，也不修改 Store schema。

## Python 启动与接口

```python
from cota.agent import Agent
from cota.webapp import create_app

agent = Agent.load_from_path('./my-bot')
app = create_app(agent, config_path='./my-bot',
                 channel_config={'web': {'enabled': True}})
app.run(host='127.0.0.1', port=5005, single_process=True)
```

应用自行提供身份适配器，不能与 `channels.web.access_factory` 同时使用。已有网站、小程序继续使用 `cota.server.create_app` 和自己的身份、群成员系统即可，不需要引入这个应用。

应用管理接口前缀 `/chat/api`，除 config/guests 外均使用 Bearer 凭据：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /config` | Bot 名称、模式、响应方式 |
| `POST /guests` | `{name}` 创建访客 |
| `GET /me` | 当前身份 |
| `GET /conversations?offset=0&limit=100` | 当前用户的会话列表，返回 has_more |
| `GET /conversations?offset=0&limit=100&summaries=1` | 列表附带 last_message、last_active、unread、read_sequence |
| `GET /conversations/{id}/summary` | 当前会话预览、未读数、事件上界 |
| `POST /conversations/{id}/read` | `{sequence}` 单调更新已读位置，不能超过已存在事件上界 |
| `POST /conversations` | `{title}` 创建会话 |
| `GET /conversations/{id}` | 会话及成员列表 |
| `POST /conversations/{id}/invite` | 群主生成或轮换邀请 |
| `POST /join` | `{invite}` 加入群 |
| `POST /conversations/{id}/remove` | 群主移除 `{user_id}` |
| `POST /conversations/{id}/leave` | 成员退出 |

配套应用启用后，核心 `/api/guests`、`POST /api/conversations` 禁用，避免绕过应用成员记录；消息、历史、提交状态与 WebSocket 接口保持统一。

第一版面向单 Bot、单服务进程，不提供好友关系、音视频、用户账号恢复、跨部署会话列表或分布式消息服务。前端无构建步骤，无新增运行依赖。


页面初次读取最近 50 条消息，可点击“加载更早消息”。可见且已连接的会话才上报已读位置；
未读数包含其他成员和 Bot 的发言，不包含自己的发言。会话列表每 15 秒刷新预览与未读数，
分页仍按会话创建时间排序。已读位置独立存于应用数据库，不进入 DST，也不触发模型执行。
凭据失效会断开连接并保留旧消息缓存及未完成输入，不使用新身份自动重发；主动退出并确认清理时才删除本地缓存。

浏览器存储配额不足时，切换会话会在当前标签页内保留尚未保存的输入；返回该会话可恢复。
最多保留 32 个非当前会话的临时状态，达到上限后须先处理这些消息才能打开新会话。
同一失败草稿的发送重试复用原 message_id，避免恢复存储后重复执行。

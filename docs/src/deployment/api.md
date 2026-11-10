# Web 聊天与应用接入

附件上传、带附件消息和授权下载使用同一会话与认证链路，完整接口见 [会话附件](../concepts/attachments.md)。

Cota 负责执行协调、上下文与用户记忆、输入去重和执行记录。外围应用负责账号、登录、会话创建、成员及访问权限。HTTP 和 WebSocket 使用同一监听端口。

## 接入已有应用

外围应用创建 user_id、session_id，并验证用户的会话访问权限。Web 入口可以注入两个异步函数：

```python
from cota.server import create_app

async def authenticate(token):
    # 接入应用自己的登录系统；失败时抛出 PermissionError。
    return await accounts.verify_token(token)

async def authorize(user_id, session_id):
    # 必须返回 True 才授权；False/None 均拒绝，也可抛出 PermissionError。
    return await conversations.can_access(user_id, session_id)

app = create_app(agent, authenticate=authenticate, authorize=authorize)
```

accounts/conversations 是外围应用的服务，不是 Cota 核心内置对象。两个函数必须同时提供。外部模式禁用 `/api/guests` 和 Cota 会话创建：前端直接使用外围已有的 token、session_id，无需在 Cota 注册用户或会话。授权函数会在历史查询、消息提交、状态查询、WebSocket 订阅和每个排队/实时帧投递前调用。凭据也会在发送和投递时重新验证；适配器应能高效处理这些只读检查。

浏览器客户端可以直接连接：

```javascript
const client = new CotaClient({
  base: 'https://your-bot.example',
  token: applicationToken,
  sessionId: applicationSessionId,
});
const messageId = await client.chat('你好');
// 外围已经有消息 ID 时可复用：await client.chat('你好', existingMessageId)
```

如果在自己的后端直接使用 SDK，入口已经受信任，不需要经过 Web 身份适配器：

```python
from cota import Application

async with Application(agent) as app:
    submission = await app.submit(
        user_id=verified_user_id, session_id=verified_session_id,
        text='你好',  # message_id 可省略，Cota 自动生成
    )
    result = await submission.wait()
```

服务中应复用一个长期存活的 Application。完整 API、生命周期和输入状态见 [应用接入契约](application.md)。

通过 CLI 启动已有应用时，也可在 channels.web 配置 `access_factory: './access.py:create_access'`。工厂是同步无参数函数，返回 `ExternalAccess(authenticate, authorize)`；文件路径相对 Bot 目录，也支持 `module:factory`。此文件属于受信任的部署代码。工厂配置不能与 create_app 的显式身份参数同时使用。

## 独立分享链接

不接已有应用时，显式启用独立的配套聊天应用：

```bash
cota run --config ./bots/weather --chat-app --host 127.0.0.1 --port 5005
```

打开 `http://127.0.0.1:5005/chat/`。应用支持访客身份、会话列表、单聊和群聊、邀请和成员管理。应用元数据独立保存于 `.cota/chat.sqlite3`，消息仍使用原 Store；详情见 [可选聊天应用](chat-app.md)。不加 `--chat-app` 时不提供默认聊天页面。

仅使用核心 Web API 且没有配置外围身份适配器时，仍可使用轻量的 GuestAccess：`POST /api/guests` 签发 30 天访客凭据，`POST /api/conversations` 签发绑定该用户的私有会话 ID，签名密钥保存在 `.cota/web.key`，不需要应用数据表。它不支持群聊或会话列表，与配套应用的 ChatAccess 是两种独立选择。密钥不应放进分享的 Bot 包。

## 数据与输入状态

核心 Store 不创建或使用 `web_credentials`、`web_conversations`、`web_inputs`。配套聊天应用的元数据位于独立应用数据库，不是 Store 的替代表。已有数据库中的旧表不会被自动删除。Store 的 deliveries 表只承接渠道回复投递，不管理账号、会话权限或输入去重；Web 本身不创建投递记录。

- `user_id`：外部验证的用户身份，决定用户记忆范围。
- `session_id`：外部对话标识，决定 DST、历史和执行顺序。
- `message_id`：一次输入的稳定 ID；省略或 null 时自动生成，显式空值无效，长度最多 255 字符。
- `event_id`：执行事实标识；输入事件使用 message_id 的稳定摘要构造，在原有事件索引中查询。

Store 通过 `(session_id, message_id)` 去重，并核对发送者、正文和媒体等输入内容。相同 ID 的相同输入返回已有状态；改变输入则拒绝。不同 Channel 使用同一 session_id 和 message_id 时也适用。

排队位置由进程内 Runner 管理，但成功接收前已保存 `user_utter`。后续状态由 `run_started` / `run_finished` 等已有执行事实恢复，不单独维护输入状态表。启动时有界恢复尚未开始的 direct 输入，已开始的运行不会自动重放。

进程退出后，已接收且尚未开始的 direct 输入可由启动恢复或原 ID 重试继续调度；已有 run_started 但无完成事实的任务按 interrupted 返回，不自动重跑。没有 ID 的请求会生成新的 ID，因此如果第一次响应丢失，客户端再次省略 ID 会被视为新消息；需要可靠重试时应在客户端预先生成并复用 ID。内置客户端已这样处理。

如果 user_utter 保存失败，提交返回错误，不能当作已接收；后续状态查询可能返回不存在，使用原 ID 重试。保存后、开始模型执行前的失败不会丢掉输入，可用相同 ID 恢复尚未开始的任务。直接使用自定义 Runner handler 时，也必须通过 Processor 或相同的事件提交契约，才能获得持久化去重。

## 配置

```yaml
channels:
  web:
    enabled: true
    transport: websocket
    concurrency: 8
    max_pending: 256
    cors_origins: []
```

未配置任何 channels 时默认启动 WebSocket WebChannel；配置了其它通道时，需要明确启用 web。endpoints.yml 的 channels 按字段覆盖 agent.yml 的通道默认设置。监听地址、端口和 TLS 使用 `cota run` 参数，不配置 channels.web.host/port。默认同源；跨源应用需要明确配置 cors_origins。小程序没有 Origin 头时也必须通过身份与会话权限验证。

当前不开放 SSE、Socket.IO 或旧 tracker/workspace 接口。公开聊天接口只返回 user_utter/bot_utter 的消息投影；原始 Events、DST、工具结果与模型请求仍由独立开发调试入口查看。

## HTTP 接口

| 接口 | 作用 |
|---|---|
| `POST /api/guests` | 仅核心 GuestAccess：签发访客凭据；配套应用使用自己的管理接口 |
| `POST /api/conversations` | 仅核心 GuestAccess：签发绑定访客的会话 ID |
| `POST /api/conversations/{session_id}/messages` | 提交消息，立即返回 202、实际 message_id 和状态查询 Location |
| `GET /api/conversations/{session_id}/messages?after_sequence=0&limit=100` | 查询授权会话的消息 |
| `GET /api/conversations/{session_id}/submissions/{message_id}` | 查询 Store 派生的提交状态 |
| `GET /api/health` | 就绪返回 200；启动未完成、退出中或启用渠道异常返回 503 |
| `GET /version` | 查看 Cota 版本，不调用模型 |
| `GET /ws` | 建立 WebSocket |
| `GET /cota.js` | 获取浏览器 WebSocket 客户端 |

消息提交、历史、状态查询和默认会话创建使用 `Authorization: Bearer <token>`。身份与会话权限规则和 WebSocket 完全一致。只启用飞书等非 Web Channel 时，仅挂载健康检查和版本接口。

### 使用 HTTP 提交消息

无需维护 WebSocket 连接即可接入脚本或后端：

```bash
curl -i -X POST 'http://127.0.0.1:5005/api/conversations/your-session-id/messages' \
  -H 'Authorization: Bearer your-token' \
  -H 'Content-Type: application/json' \
  --data '{"text":"你好","message_id":"client-message-001"}'
```

响应为当前提交回执，例如：

```json
{"session_id":"your-session-id","message_id":"client-message-001","status":"queued","error":null,"duplicate":false}
```

`202 Accepted` 表示输入已保存并被接收，不表示模型已经完成或用户已读。响应头 `Location` 指向现有的 submissions 状态接口；带同一 Bearer 凭据查询它，再通过 messages 接口取得回复。重复提交同一 ID、相同内容时仍返回 202，`duplicate` 为 true，状态可能已经是 completed，不重新执行模型。不同内容使用同一 ID 返回 409。

请求体只允许 `text`、`message_id`、`mentioned`、`reply_to`。`text` 必填且为 1–32768 字符的非空文本；HTTP 请求体上限 256 KiB。`message_id` 省略或 null 时自动生成。群聊可用 `mentioned: true` 明确 @ Bot，`reply_to` 为引用消息 ID；普通群消息可能仅返回 recorded，是否触发执行由已有群聊策略决定。不能在正文里传入身份或覆盖 session_id。

提交后 HTTP 客户端断线不会取消已接收的执行。HTTP 和 WebSocket 共用去重与消息广播，因此可以 HTTP 发送、WebSocket 接收，也可以完全用 HTTP 查询历史。请求结果丢失时使用原 message_id 重试；不要重新生成 ID。队列满、进程重启等恢复边界与前述 WebSocket 契约相同。

URL 中的 session_id、message_id 应分别进行百分号编码（包括 `/`、`%` 等字符），服务端只解码一次。历史查询额外支持 `until_sequence`：首屏取得 `through` 后，将它作为后续页的 until_sequence，配合返回的 cursor 继续分页，可以固定查询上界。limit 为 1–500，游标必须为非负整数；事件流跳号或当前页没有聊天消息并不表示结束，应以 has_more 为准。

### 错误与就绪检查

HTTP 错误统一返回 JSON，`error` 为稳定代码；部分输入错误附带可读的 `message`。不要依赖 message 文案编写客户端逻辑。

| HTTP 状态 | error | 处理方式 |
|---|---|---|
| 400 | invalid_request | 修正 JSON、字段类型或分页参数 |
| 403 | unauthorized / origin_not_allowed | 检查凭据、会话权限或 cors_origins |
| 404 | not_found | 接口或提交记录不存在 |
| 405 | method_not_allowed | 检查 HTTP 方法；Allow 头列出可用方法 |
| 409 | input_conflict / run_in_progress | 不要修改已有消息 ID 的内容；未结束执行需先协调，不能盲目重跑 |
| 413 / 415 | payload_too_large / unsupported_media_type | 减小请求体，使用 application/json |
| 429 | busy | 根据 Retry-After 稍后用原 message_id 重试 |
| 503 | not_ready | 服务正在启动或关闭，稍后重试 |
| 500 | internal_error | 查看服务日志；公开响应不包含内部异常和堆栈 |

`/api/health` 是服务就绪检查，响应保留 success、bot、channels；渠道异常只公开 channel_failed，原始原因写入日志。它不探测模型供应商，也不执行收费请求，不能代表模型或外部工具一定可用。服务退出时停止接收新输入，按 Application 的有界关闭规则等待已有执行，随后清理 Web 观察任务；HTTP 监听等待方被取消不会丢弃这段清理。

创建服务器时会提前检查 Channel 配置、enabled 类型、Web transport 和 cors_origins。跨域列表必须是完整的 http(s) origin（不含路径、账号、查询或通配符）。允许的跨域前端可读取 Location 和 Retry-After 响应头。不传 config_path 时使用已加载 Agent 的 config_path，访客签名密钥随 Bot 目录保存。

## WebSocket 协议

建立连接后 10 秒内发送：

```json
{"type":"resume","token":"...","session_id":"...","after_sequence":0}
```

验证身份与会话权限后，先补取历史，再发出 `ready`：

```json
{"type":"ready","session_id":"...","cursor":12}
```

提交消息，message_id 可省略：

```json
{"type":"send","message_id":"client-id","text":"你好"}
```

身份在 resume 绑定，send 不允许携带 user_id、sender_id。默认向初始会话发送；也可携带已订阅会话的 session_id。提交回执包含实际使用的 message_id，状态可能为 queued/recorded/running/completed/limited/failed/interrupted。队列满返回 busy，可稍后使用原 ID 重试。

聊天消息：

```json
{"type":"message","session_id":"...","event_id":"...","sequence":5,"role":"bot","text":"你好！","message_id":null}
```

用户消息的 message_id 关联输入；Bot 消息以 event_id 标识。客户端按 event_id 去重，按 sequence 排序。sequence 属于完整执行事件流，聊天消息跳号正常。

## 运行与恢复范围

同会话的明确请求按 FIFO 执行、不同会话有限并发；群聊主动参与任务排在明确请求之后，不抢占已开始的执行。每轮独立绑定用户记忆与工具。模型没有内置定时或后台任务工具。可信应用可独立管理 SchedulerService 后端；定时投递未接入 Web 会话。

断开连接不取消运行。回复先保存到 Store 再推送；重连通过 cursor 补取，发送失败不触发模型/工具重跑。每个连接有独立有界发送队列，历史回放期间的实时消息另有有界缓冲，不持锁等待慢连接。超出缓冲或发送失败会断开慢连接，再从持久历史补取；客户端仍需按 event_id 去重。文本上限 32768 字符，帧上限 256 KiB。

单进程服务，不支持多个执行进程共同消费同一会话。已经持久化但执行中断的输入不会自动重放外部副作用；若旧 DST 仍为 running，必须先确认旧执行器已停止并人工协调，或新建会话。

旧 use_proxy_user 模拟循环不属于已标识消息的执行入口，现在会明确拒绝，避免绕过输入记录重复运行模型。需要模拟对话时应通过独立的评测流程提交正常消息。


### 多会话订阅与容量

同一连接可以发送 `{"type":"subscribe","session_id":"room-2","after_sequence":0}`，
取消订阅使用 `{"type":"unsubscribe","session_id":"room-2"}`。每次订阅、发送与投递都重新鉴权；
应用继续管理身份与成员关系。每个会话独立先回放、再 ready、再投递回放期间的实时帧。
客户端按 session_id 分流并按 event_id 去重。任一会话权限撤销会关闭整个连接，重连时只订阅仍有权限的会话。

`channels.web` 可配置 `max_connections`（默认 1024，上限 10000）、
`max_connections_per_user`（默认 8，上限 100）、`max_subscriptions`（每连接默认 32，上限 256）。
握手中的连接也计入总连接数；容量满返回 busy。`/api/health` 的 web 字段仅暴露连接数、订阅数与容量，不含身份。

### 最近消息与向前翻页

`GET /api/conversations/{id}/messages?recent=1&limit=50` 获取最近一页；
用返回的 `cursor` 请求 `?before_sequence=<cursor>&limit=50` 获取更早消息。
每页按时间正序返回，`has_more` 表示仍有更早消息；`through` 是快照的事件上界。
不要将 backward 参数与 after_sequence/until_sequence 混用。
resume/subscribe 可传 `recent:true` 只回放最近 50 条，ready 同时包含 has_more。
已持有 cursor 的重连应使用 after_sequence 补齐断线期间全部增量。

内置 CotaClient 初次使用最近 50 条，`await client.loadOlder()` 加载更早消息，触发 history 事件。
浏览器缓存默认最多 200 条（maxCachedMessages 最大 500），当前消息视图最多 1000 条；
未完成输入单独保留，最多 100 条，达到上限拒绝新增输入，不删除已有输入。
缓存损坏会保留原始存储并提示恢复；配额不足时保留当前标签页中的待发输入并报告错误，
调用方应保留草稿并让用户重试。临时服务错误不会删除待发输入；只有终态回执确认完成。


实时投递按已持久化的消息前缀补齐：如果较高 sequence 的通知先到达，服务端先查询并投递此前缺少的聊天消息，
再发送较高 sequence。执行回调乱序不会让客户端游标越过尚未收到的已保存回复。

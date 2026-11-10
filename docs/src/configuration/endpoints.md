# endpoints.yml

`endpoints.yml` 描述模型服务、存储和部署连接。`Agent.load_from_path()` 使用 `base_store` 创建 Store 和用户记忆，使用 `llms` 创建模型客户端，并把 `embeddings` 提供给 Policy；Channel 配置由 CLI 或应用入口加载。

## 可用的最小配置

```yaml
base_store:
  type: sql
  dialect: sqlite
  db: workspace/sessions.db
  snapshot_interval: 100
llms:
  default:
    type: openai
    key: replace-with-provider-key
    apibase: https://api.example.com/v1
    model: replace-with-tool-capable-model
channels:
  web:
    enabled: true
    transport: websocket
```

示例模型地址和凭证是占位值，必须改为实际模型服务。`key`、`apibase`、`model` 必须是非空文本；`${API_KEY}` 等环境变量引用会被拒绝。无需配置 `COTA_API_KEY`，它也不是 Web 会话认证方式。

## base_store

`Store.create()` 默认使用内存后端。需要重启后保留会话时显式选择 SQL，并给出 dialect：

| 字段 | 作用 |
| --- | --- |
| `type` | `memory` 或 `sql`；省略时为 memory |
| `snapshot_interval` | 快照事件间隔，默认 100 |
| `dialect` | SQLAlchemy dialect；建议 SQLite 使用 `sqlite` |
| `db` | SQLite 文件路径、`:memory:` 或服务器数据库名 |
| `host` / `port` | 服务器数据库地址 |
| `username` / `password` | 服务器数据库凭证 |
| `login_db` / `query` | SQLStore 的可选连接设置 |

SQLite 相对文件路径由 `Agent.load_from_path()` 转换为 Bot 目录下的绝对路径，Store 与 UserMemory 复用它。单独调用 `Store.create()` 不做 Bot 路径解析。SQL 配置省略 dialect 时，Store 与记忆工厂的缺省值不同，因此应显式填写 dialect 和 db。

服务器数据库示例：

```yaml
base_store:
  type: sql
  dialect: mysql+pymysql
  host: 127.0.0.1
  port: 3306
  db: cota
  username: cota_user
  password: replace-with-database-password
```

这只是存储片段，需要与模型配置合并。`login_db` 和 `query` 当前仅由 SQLStore 使用，不会传给 SQLUserMemory。数据库权限和部署连接可用性由部署方准备。

## llms

`llms` 是名称到配置的映射，供 `dialogue.llm`、Policy 和 knowledge 引用。

| `type` | 支持字段 |
| --- | --- |
| `openai`（默认） | `key`、`apibase`、`model`、可选 `thinking` |
| `openai-rag` | 上述字段，加必填 `knowledge_id` 和可选 `rag_prompt` |
| `custom` | `key`、完整 HTTP URL `apibase`、`model`，其余配置传入 JSON 请求体 |

OpenAI 类型的 `apibase` 为 API base URL；custom 类型直接 POST 到该 URL。custom 服务应返回 `content` 和可选的 OpenAI 风格 `tool_calls`。`openai-rag` 依赖服务商支持 retrieval 扩展。不是所有看起来兼容 OpenAI 的服务都支持工具调用或该扩展。

`max_tokens` 等每轮对话设置放在 `agent.yml` 的 `dialogue` 中；它们不是 openai factory 自动透传的额外字段。LLM 使用完成后由 Agent cleanup 关闭。

`vision: true` 是可选的 Cota 模型能力声明，默认 false。启用后，上传的小图片可作为真实视觉输入传给该对话模型；该字段不作为供应商请求参数发送。纯文本主模型可保持 false，使用 Skill 的专门视觉服务，详见 [附件与模型理解](../concepts/attachments.md)。

### 评测模型

`cota eval` 和 `cota eval judge` 自动优先选择 `llms.evaluator`；未定义 evaluator 时使用 `llms.default`。不需要命令行指定评委。被测 Bot 仍使用 agent.yml 中的 `dialogue.llm`，评委配置不会替换 Bot 的对话模型。

需要独立评委时，在已有 llms 映射下添加：

```yaml
llms:
  default:
    type: openai
    key: replace-with-bot-provider-key
    apibase: https://api.example.com/v1
    model: replace-with-tool-capable-model
  evaluator:
    type: openai
    key: replace-with-judge-provider-key
    apibase: https://api.example.com/v1
    model: replace-with-judge-model
```

不使用独立评委就不添加 evaluator，不要保留空配置。已配置的 evaluator 不完整时报告配置错误，调用失败时记录评判错误，不静默切换 default。评委需支持文本与 JSON 对象输出，不执行 Bot 的工具循环。详见[Bot 对话评测](../development/evaluation.md)。

## embeddings

需要向量检索的 Policy 可以引用命名 embedding 资源：

```yaml
embeddings:
  policy_vectors:
    type: openai
    key: replace-with-provider-key
    apibase: https://api.example.com/v1
    model: replace-with-embedding-model
    dimensions: 1024
```

`type` 当前只支持 `openai`，`dimensions` 可省略，填写时必须为正整数；其他字段不被接受。训练数据只保留资源身份哈希，不把凭证保存到 Policy 产物。策略引用和训练流程见 [Policy 配置](policy.md)。

## channels

CLI 按 `agent.yml`、`endpoints.yml` 的顺序合并每个 channel；后者覆盖同名字段。`Agent.load_from_path()` 本身不会启动或保留一个 ChannelManager。SDK 使用 `create_app(agent, channel_config=...)` 时传入 channels 内部映射，例如 `{"web": {"enabled": True}}`。

内置类型包括 `web`、`feishu`、`cmdline`；其他平台可安装独立 Channel 插件。映射键是实例名，`type` 指定实现，省略时使用实例名；也可使用互斥的 `factory: "module:callable"`。`enabled` 必须是布尔值，缺省为 false；安装插件不会自动启用它。类型只在已启用实例创建时加载，未安装的已启用类型会报错。实例名与类型名为最多 64 字符的小写标识符，可使用数字及 `_` / `-` 分隔，从字母开始。内置 Web 保留 `web` 实例名，不能别名或覆盖。

外部插件配置示例（需先在运行 Cota 的 Python 环境安装相应包）：

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

该示例是通用可信网关协议，非真实平台的原生实现；完整安装、验签和可靠投递契约见 [Channel 插件开发](../development/channel-plugins.md)。插件 HTTP 回调位于 `/channels/{实例名}`，无需启用 Web Channel。

Web 主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `enabled` | 是否启用 |
| `transport` | `websocket`；`auto` 也解析到 WebSocket |
| `cors_origins` | 明确的 http(s) origin 列表，不含路径和通配符 |
| `access_factory` | 自定义访问控制工厂，详见应用 API |
| `concurrency` / `max_pending` | 应用执行并发与输入队列容量，默认 8 / 256 |

Web 不接受旧 `host`、`port`；监听地址由 `cota run --host ... --port ...` 设置。未提供 channel 配置时 run 默认启用 Web；显式提供配置时必须至少启用一个 channel。Web 使用 HTTP API + WebSocket；没有 SSE/Socket.IO 回退。

飞书配置片段：

```yaml
channels:
  feishu:
    enabled: true
    app_id: replace-with-feishu-app-id
    app_secret: replace-with-feishu-app-secret
    allow_from: [ou_replace_with_allowed_user]
```

飞书需安装可选依赖。`allow_from: []` 的权限语义为拒绝所有人，`["*"]` 允许全部用户，其他列表只允许指定用户。标准 ChannelManager 启动时还会拒绝已启用飞书的缺省或空列表，因此实际接入需填写允许用户。群聊的 dialogue mode 和身份校验见 [飞书部署](../deployment/feishu.md)。内置 [Web app](../deployment/chat-app.md) 是可选界面，不是启动 Bot 服务的必需项。

实现入口：`cota/agent.py`、`cota/store.py`、`cota/llm/factory.py`、`cota/policy/resources.py`、`cota/__main__.py`、`cota/server.py`。

相关文档：[配置总览](overview.md) · [Agent 配置](agent.md) · [用户记忆](../components/user_memory.md) · [应用 API](../deployment/api.md)

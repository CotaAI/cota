# 模块地图与职责

这份地图用于定位代码和判断新功能应该放在哪一层。源路径均相对仓库根目录。

| 模块 / 类 | 主要代码 | 职责与边界 |
| --- | --- | --- |
| CLI | `cota/__main__.py`、`templates.py` | init、shell、run、train、annotate、eval；模板定位和运行资源清理 |
| Agent | `cota/agent.py`、`config.py` | 加载 Bot 配置，持有模型、工具、Policy、Store 和用户记忆；不等同于 Pi Agent |
| Application / Submission | `cota/application.py` | 长期复用的服务接入对象；提交、等待、历史、回执和生命周期 |
| InboundMessage / OutboundMessage | `cota/channels/events.py` | 渠道无关的输入身份、会话、消息 ID 与输出路由 |
| ChannelRunner / MessageBus | `cota/channels/runner.py`、`queue.py` | 同会话排队、跨会话并发、接收和调度；不编写业务提示词 |
| GroupConversation / ParticipationJudge | `cota/group.py`、`participation.py` | 普通群消息记录、@ 响应、主动参与节流与过期判断 |
| Processor | `cota/processor.py` | 恢复会话、记录输入、绑定用户工具视图、衔接 Runtime 与回复 |
| PiAgentRuntime / PiBridge | `cota/runtime/pi_runtime.py`、`pi_bridge.py` | Python 协调与 JSONL 桥；每次模型请求前准备业务指导和上下文 |
| Pi worker | `cota/runtime/pi/` | 官方 Agent Core 循环；复用 coding-agent 的 Skill loader 与八个官方工具工厂 |
| DST | `cota/dst.py` | `apply_event()` 驱动状态和上下文投影；记录运行中的事实，不替代存储后端 |
| Event / Trace | `cota/events/`、`trace.py`、`runtime/pi_trace.py` | 稳定事实契约、来源关联与按 run 聚合；无独立 Action 层 |
| Store / Snapshot | `cota/store.py`、`snapshots.py`、`inputs.py`、`run_metadata.py` | 事件追加、恢复缓存、输入去重、运行资源目录和历史查询 |
| Policy | `cota/policy/` | 标注解析、train/load/guidance、策略扩展、预算和实际注入记录 |
| Evaluation | `cota/evaluation/` | 独立执行对话验证、LLM Judge、进度、证据与报告、重评和版本对比；不向 Bot 注入评测要求，不自动优化 Bot |
| 标注文件接口 | `cota/annotation_files.py`、`annotation_cli.py` | 对话导出为编辑草稿，导入校验成 Policy；不写人工标注 Event |
| ExecutionEnvironment | `cota/executor/environment.py` | 可信 none/machine 环境绑定；不把 cwd 当作沙箱 |
| Tool / ToolRegistry | `cota/executor/tools/` | 工具 schema、权限、执行期身份视图与结果；Skill 文本不授予权限 |
| MCP / 工具进程 | `cota/executor/mcp*.py`、`tool_process.py`、`tool_servers/` | 真实工具能力和独立依赖进程；负责连接与进程生命周期 |
| UserMemory | `cota/executor/user_memory.py` | 按 user_id 的跨会话偏好；不同于 Store 的会话事件 |
| LLM / Knowledge | `cota/llm/`、`knowledge/` | 模型服务适配、请求观察；可选模型辅助知识，不自带事实检索库 |
| Channel / DeliveryDispatcher | `cota/channels/`、`delivery_store.py` | web、feishu、cmdline 的接入与输出；飞书回复持久化重试 |
| Server | `cota/server.py` | 单 HTTP listener、授权后的消息接口、WebSocket、健康检查；不公开原始 DST |
| 可选聊天应用 | `cota/webapp/` | 访客、会话列表、群成员与页面；独立应用数据库，不复制对话正文 |
| Debug | `cota/debug/`、`execution_logging.py` | 只读查看事件、Skill 目录、模型诊断、DST 与快照；不驱动执行 |

## 一条消息中的关系

```text
已验证 user_id + 已授权 session_id + 稳定 message_id
  → InboundMessage
  → Application / ChannelRunner（同会话顺序）
  → Processor
  → Store 恢复 DST → 追加 user_utter
  → 需要回复时启动 PiAgentRuntime
      → Pi 请求模型前：Policy.guidance + 基础 prompt + 当前上下文
      → 模型提出调用 → 保存 tool_started → 执行工具 → 保存 tool_result
      → Pi 使用实际结果继续请求模型
      → bot_utter → 保存 → 应用/Channel 投递
```

`session_id` 隔离对话，`user_id` 隔离个人记忆，`message_id` 去重输入。
群聊多个 user_id 共用一个 session_id；成员访问权由外围维护，群上下文不自动读取个人记忆。
完整细节见 [执行流程](execution-flow.md)、[应用契约](../deployment/application.md)。

## 新功能放在哪里

| 要增加的功能 | 放置位置 |
| --- | --- |
| 一个新的业务能力及 SOP | Bot 的 `skills/`，实际操作能力接入 Tool/MCP |
| 运营期望的业务判断和回复 | Bot 的 `policy/`；检索/选择算法扩展 Policy 类 |
| 平台消息格式、认证适配、回复 API | Channel；可复用应用协调放 Application |
| 会话列表、邀请、成员管理 | 外围应用或可选 Web app |
| 可重放的执行事实 | Event + DST 应用规则 + Store 合同测试 |
| 模型请求调试细节 | 独立 Debug 诊断，避免扩张核心 Event |
| 新的模型供应商 | LLM adapter，保持统一返回与 observation/close 契约 |
| 验证集、评分、评测进度与版本对比 | `cota/evaluation/`；进度是可选观察回调，不新增 DST Event |
| 自动生成优化候选与版本应用 | 后续 RSI；复用评测产物，不直接改写已保存事件或运行中的 Bot |

开发前阅读 [测试与验证](../development/testing.md)，尤其不要用旧 Action、Skill 激活/完成事件重新引入第二套业务执行循环。

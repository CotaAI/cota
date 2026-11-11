# Pi runtime

Cota 使用 Pi Agent Core 控制模型—工具循环，并复用 Pi coding-agent 的 Skill 发现、解析、目录格式化、token 估算与压缩组件，以及八个官方工具工厂（read/write/edit/bash/grep/find/ls/powershell）。Cota 没有接入 `AgentSession`，不会写 Pi 会话文件，也不会加载 coding-agent 的完整交互式工作环境。压缩切分和摘要由 Pi 公共 API 完成，Pi 在 Node 内直接调用主对话和摘要模型；Cota 提供配置、提交事件并恢复投影，详见 [执行流程](execution-flow.md)。

## 版本与运行环境

当前 `cota/runtime/pi/package.json` 固定以下依赖为 **1.4.0**：

- `@earendil-works/pi-agent-core`
- `@earendil-works/pi-ai`
- `@earendil-works/pi-coding-agent`

Node 要求为 **>= 22.19.0**。源码开发在准备好 Node 后执行：

```bash
python -m cota.runtime.pi_setup
```

运行时只定位和校验已有依赖，不在收到请求时下载或安装。平台 wheel 内置专用 Node 和 Pi 依赖；源码开发使用自行准备的 Node 和 npm 依赖。安装方式见 [部署指南](../deployment/guide.md)。

## 构建发布包

在仓库根目录使用 Python 3.12+ 执行：

```bash
uv pip install build
python scripts/bundle_runtime.py
COTA_RUNTIME_DIR="$PWD/.build/pi-runtime" python -m build
```

`build` 是构建前端；隔离构建环境会按 `pyproject.toml` 安装 Hatchling。bundle 脚本按 `scripts/node-runtime.json` 下载并校验固定 Node 发行包，用随包的 npm 安装锁定依赖，运行 staged worker 测试，然后输出 `.build/pi-runtime`。默认下载缓存为 `.build/downloads`。输出目录必须尚不存在；重复准备时使用 `--output` 指定新的目录，并让 `COTA_RUNTIME_DIR` 指向它。

`python -m build` 输出 sdist 和平台 wheel 到 `dist/`；仅需 wheel 时加 `--wheel`。构建钩子校验 runtime 的平台、版本和输入文件哈希，将它装入 `cota/runtime/_vendor`。构建阶段需要下载资源，但安装后运行不依赖系统 Node/npm，也不会在线补装 runtime。

当前发布 target 为 macOS arm64/x64 和 Linux arm64/x64，必须在对应平台原生构建，不能把一个平台的 bundle 用于另一个平台的 wheel。`.github/workflows/runtime-wheels.yml` 为这些 target 设置原生 runner，构建后在新 venv 安装 wheel、运行 `pip check`，再从源码目录外执行 `scripts/smoke_installed.py`。smoke 隐藏系统 Node/npm 并禁止运行时网络，验证内置 runtime、模板和离线执行。发布步骤见 [发布流程](https://github.com/CotaAI/cota/blob/main/docs/releases/README.md)。

## Python 与 Node 的边界

`PiBridge` 为每轮启动 worker，通过 JSON-lines 交换带确认的请求和独立的流式通知。普通 `openai` 端点由 Pi 官方 provider 在 Node 内直接组装请求并读取 SSE；主对话和压缩摘要走同一模型通道。Cota 在 `prepareRequest` 前后提供 Policy 与工具范围，通过 `onPayload` 观察实际请求，并接收完整模型输出和执行事实。Python 专用的 `custom`、`openai-rag` 端点继续使用其适配器传输，不伪装成流式接口，也不引入另一套 Agent 循环。

桥接独立处理顺序请求和有界的公开文字通知。慢速或断开的展示端不能阻塞执行确认；拥塞时允许舍弃预览片段，完整已提交回复仍为准。连接关闭、取消、超时或错误会结束本轮，通过 AbortSignal 让 Pi 清理模型连接和命令进程，再回收 worker。

桥接以 64 KiB 缓冲分段收发，独立限制每条 JSON 帧最多 128 MiB；不会把 asyncio 的行缓冲上限当作模型上下文容量。超长、截断或无效帧明确报错，不确认未完成的请求。模型工作上下文另受 token、默认 32 MiB 序列化体积、8 张图片及16 MiB图片字节预算约束，复用 Pi 压缩后再继续请求。传输帧上限与工作上下文预算是不同边界。

| Pi | Cota |
| --- | --- |
| 原生模型调用、流式解析、模型—工具循环、顺序工具执行 | 模型配置、业务指导、执行授权与 Python 扩展能力 |
| Skill 目录与八个原生工具实现 | 执行环境、资源根目录、读取证据与授权 |
| 本轮暂态消息 | 事件投影、快照、历史恢复 |
| 调用 `prepareRequest`，组装当前工作上下文 | 从已提交 DST 重算 Policy guidance 与工具 schema |

工具以顺序模式执行。Pi 的 `beforeToolCall` 钩子让 Cota 在副作用前保存校验后的参数；checkpoint 失败不会获得确认。

Pi 1.4 区分可执行工具和供应商工具声明：`AgentContext.tools` 绑定执行器，provider 从 system 消息的 `toolsAdded` / `toolsRemoved` 解析模型可调用的能力。Cota 的 `prepareRequest` 重建指导时，使用 Pi 的 `createInitialSystemMessage` 和 `toToolDeclaration` 同步声明当前完整工具集合，避免只保留 prompt 文字却丢失实际 tools。每次 Policy 或工具范围变化后，下一次真实请求也必须反映该变化。

模型回复同时包含公开文字和工具调用时，完整 assistant 消息仍归属于第一条 `tool_started`；另保存一条以 `llm_event_id` 指向它的 `bot_utter` 用于历史展示和投递。两者同次提交后才执行工具；这条公开发言不再生成第二份模型上下文。隐藏推理不属于公开文字。

原生请求单次默认总时限180秒、默认不自动重试；空行保活、SDK 退避以及请求观察钩子的等待不能延长该时限，详见 [endpoints.yml](../configuration/endpoints.md)。初始历史只同步一次；普通 prepare 只返回 system 指导、工具声明和已授权的附件位置，不往返传输包含图片的整份历史。压缩后才从 Cota 接收新的上下文投影。Debug 模式额外传回一次实际供应商请求。原生工具产生的图片结果仍按现有工具记录协议传递，尚未引入通用二进制资源协议。

`text_delta` 只作为实时预览发送给支持它的 Channel；思考、工具参数等增量不作为用户回复。完整回复提交后以同一 request_id 替换预览，不新增逐 token Event。必要的 Pi 推理签名和续接内容保存在来源事件的可选 `llm.continuation` 中，用于恢复模型协议；普通聊天历史不展示它，普通无签名文本不会增加该字段。

## Skill 资源边界

发现范围来自 `Agent.skill_paths`，默认仅为该 Bot 的 `skills/`。调用 Pi 的加载器时关闭默认全局目录，检查真实路径，拒绝越过资源根目录的符号链接。

`environment.type: none` 下，read 仅能读取已发现 Skill 目录的普通文件；machine 下，同一个 read 还可读取宿主机业务文件，与其他可用原生工具使用同一个工作目录。machine 工作目录不构成沙箱。八个名称始终保留给 Pi；personal 的 machine 环境即使没有 Skill，也会按依赖可用性提供工具。配置与边界见 [工具与执行环境](tool-adapters.md)。

`skills.mjs` 只负责发现与格式化目录；`tools.mjs` 使用官方 ToolDefinition 工厂构造工具，保留参数转换及 prompt guidelines。Cota 将这些 guidelines 与执行环境说明加入每次 prepare 的 system prompt，不引入完整 coding-agent system prompt。

成功读取的结果保存资源种类、所属 Skill、路径、内容哈希及必要的范围信息。这些字段描述“读到了什么”，不证明业务 SOP 已执行。`active_skill` 仅是最近成功阅读的 Skill 标签。

## 配置与排查

`dialogue.runtime` 仅支持 `pi`，省略时也使用 Pi；`legacy` 已移除。`pi_node` 可指定 Node 可执行文件，`run_timeout_seconds` 限制整轮桥接时长。模型调用次数、上下文大小和回复 token 由 [Agent 配置](../configuration/agent.md) 控制。

运行记录查看 Cota Store / Trace；原始模型请求诊断属于单独的 debug 数据，不应把 Pi 目录当会话数据库。

实现入口：`cota/runtime/pi_bridge.py`、`cota/runtime/pi_runtime.py`、`cota/runtime/pi/engine.mjs`、`cota/runtime/pi/model.mjs`、`cota/runtime/pi_models.py`、`cota/runtime/pi/skills.mjs`、`cota/runtime/pi/tools.mjs`、`cota/runtime/pi_distribution.py`。

相关文档：[执行流程](execution-flow.md) · [DST](dst.md) · [Skills](../skills/overview.md) · [Tool 适配](tool-adapters.md)

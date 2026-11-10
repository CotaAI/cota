# Pi runtime

Cota 使用 Pi Agent Core 控制模型—工具循环，并复用 Pi coding-agent 的 Skill 发现、解析、目录格式化、token 估算与压缩组件，以及八个官方工具工厂（read/write/edit/bash/grep/find/ls/powershell）。Cota 没有接入 `AgentSession`，不会写 Pi 会话文件，也不会加载 coding-agent 的完整交互式工作环境。压缩切分和摘要由 Pi 公共 API 完成，Cota 对接模型、提交事件并恢复投影，详见 [执行流程](execution-flow.md)。

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
python -m pip install build
python scripts/bundle_runtime.py
COTA_RUNTIME_DIR="$PWD/.build/pi-runtime" python -m build
```

`build` 是构建前端；隔离构建环境会按 `pyproject.toml` 安装 Hatchling。bundle 脚本按 `scripts/node-runtime.json` 下载并校验固定 Node 发行包，用随包的 npm 安装锁定依赖，运行 staged worker 测试，然后输出 `.build/pi-runtime`。默认下载缓存为 `.build/downloads`。输出目录必须尚不存在；重复准备时使用 `--output` 指定新的目录，并让 `COTA_RUNTIME_DIR` 指向它。

`python -m build` 输出 sdist 和平台 wheel 到 `dist/`；仅需 wheel 时加 `--wheel`。构建钩子校验 runtime 的平台、版本和输入文件哈希，将它装入 `cota/runtime/_vendor`。构建阶段需要下载资源，但安装后运行不依赖系统 Node/npm，也不会在线补装 runtime。

当前发布 target 为 macOS arm64/x64 和 Linux arm64/x64，必须在对应平台原生构建，不能把一个平台的 bundle 用于另一个平台的 wheel。`.github/workflows/runtime-wheels.yml` 为这些 target 设置原生 runner，构建后在新 venv 安装 wheel、运行 `pip check`，再从源码目录外执行 `scripts/smoke_installed.py`。smoke 隐藏系统 Node/npm 并禁止运行时网络，验证内置 runtime、模板和离线执行。发布步骤见 [发布流程](https://github.com/CotaAI/cota/blob/main/docs/releases/README.md)。

## Python 与 Node 的边界

`PiBridge` 为每轮启动 worker，通过有序、带确认的 JSON-lines 消息交换请求。Pi 发出 `prepare`、`model`、`tool`、`authorize_tool`、`tool_result` 和事件通知；Python 在成功处理并提交需要持久化的状态后回复。连接关闭、超时或错误会结束本轮；先通过输入流关闭触发 AbortSignal，让 Pi 清理命令进程，再回收 worker。

桥接以 64 KiB 缓冲分段收发，独立限制每条 JSON 帧最多 128 MiB；不会把 asyncio 的行缓冲上限当作模型上下文容量。超长、截断或无效帧明确报错，不确认未完成的请求。模型工作上下文另受 token 和默认 32 MiB 序列化体积预算约束，复用 Pi 压缩后再继续请求。传输帧硬上限、工作上下文字节预算与模型 token 容量是三个不同边界。

| Pi | Cota |
| --- | --- |
| 模型—工具循环、参数校验、顺序工具执行 | LLM 客户端与 Python 扩展工具能力 |
| Skill 目录与八个原生工具实现 | 执行环境、资源根目录、读取证据与授权 |
| 本轮暂态消息 | 事件投影、快照、历史恢复 |
| 调用 `prepareRequest` | 每次请求重算 Policy guidance 与工具 schema |

工具以顺序模式执行。Pi 的 `beforeToolCall` 钩子让 Cota 在副作用前保存校验后的参数；checkpoint 失败不会获得确认。

## Skill 资源边界

发现范围来自 `Agent.skill_paths`，默认仅为该 Bot 的 `skills/`。调用 Pi 的加载器时关闭默认全局目录，检查真实路径，拒绝越过资源根目录的符号链接。

`environment.type: none` 下，read 仅能读取已发现 Skill 目录的普通文件；machine 下，同一个 read 还可读取宿主机业务文件，与其他可用原生工具使用同一个工作目录。machine 工作目录不构成沙箱。八个名称始终保留给 Pi；personal 的 machine 环境即使没有 Skill，也会按依赖可用性提供工具。配置与边界见 [工具与执行环境](tool-adapters.md)。

`skills.mjs` 只负责发现与格式化目录；`tools.mjs` 使用官方 ToolDefinition 工厂构造工具，保留参数转换及 prompt guidelines。Cota 将这些 guidelines 与执行环境说明加入每次 prepare 的 system prompt，不引入完整 coding-agent system prompt。

成功读取的结果保存资源种类、所属 Skill、路径、内容哈希及必要的范围信息。这些字段描述“读到了什么”，不证明业务 SOP 已执行。`active_skill` 仅是最近成功阅读的 Skill 标签。

## 配置与排查

`dialogue.runtime` 仅支持 `pi`，省略时也使用 Pi；`legacy` 已移除。`pi_node` 可指定 Node 可执行文件，`run_timeout_seconds` 限制整轮桥接时长。模型调用次数、上下文大小和回复 token 由 [Agent 配置](../configuration/agent.md) 控制。

运行记录查看 Cota Store / Trace；原始模型请求诊断属于单独的 debug 数据，不应把 Pi 目录当会话数据库。

实现入口：`cota/runtime/pi_bridge.py`、`cota/runtime/pi_runtime.py`、`cota/runtime/pi/engine.mjs`、`cota/runtime/pi/skills.mjs`、`cota/runtime/pi/tools.mjs`、`cota/runtime/pi_distribution.py`。

相关文档：[执行流程](execution-flow.md) · [DST](dst.md) · [Skills](../skills/overview.md) · [Tool 适配](tool-adapters.md)

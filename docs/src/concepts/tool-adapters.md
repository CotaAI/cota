# Tool 适配与能力边界

Skill 描述业务做法，Tool 执行具体操作。Pi 提供 read、write、edit、bash、grep、find、ls、powershell 八个底层工具，Cota 为它们绑定执行环境；唯一内置自定义工具 `http_request` 使用 Pi 标准工具定义在 Node 中执行；应用仍可通过 Python 注册自定义扩展。Pi 选择和校验调用，Cota 在执行前检查许可并保存开始事件。

## Pi 原生工具与执行环境

`deploy` 表达使用模式，与运行机器的位置无关：

| 模式 | 面向谁 | 默认原生工具环境 |
| --- | --- | --- |
| `personal` | 部署者自己，本机和个人云服务器均适用 | `machine`：部署机器，Bot 目录下的 `files/` 为 cwd |
| `service`（省略时的默认值） | 提供给他人、客服或群组 | `none`：只读已发现的 Skill 资源 |

最简单的个人配置是 `deploy: personal`。需要调整工作目录等选项时：

```yaml
deploy: personal
environment:
  type: machine
  workspace: ./files
  timeout_seconds: 60
  shell: auto  # 可省略；提供官方实现支持且当前机器可用的 Shell
```

相对路径以 Bot 配置目录为基准；首次执行会创建工作目录。可用工具使用同一个起始目录，与保存数据库、日志的 `workspace/` 分开。没有 Skill 时也可以使用宿主机工具。模型无需传环境名称、用户 ID 或设备 ID。

宿主机工具按实际能力提供：

| 工具 | 可用条件 |
| --- | --- |
| read / write / edit / ls | machine 环境，使用官方文件工具 |
| grep | Pi 可找到并运行 ripgrep (`rg`) |
| find | Pi 可找到并运行 `fd`，Linux 的 `fdfind` 也由 Pi 原生识别 |
| bash | Pi 的 `getShellConfig()` 能选择可用 Shell |
| powershell | Pi 1.4.0 的官方实现仅支持 Windows，并且能找到 PowerShell |

`environment.shell` 支持 `auto`（默认，提供可用 Shell）、`bash`、`powershell`、`both`。显式要求的 Shell 不可用会在主 Agent 模型循环开始前报错；auto 模式和搜索工具缺失依赖时会省略对应工具，并记录原因。macOS 上即使有 pwsh，Pi 1.4.0 的官方 PowerShell 工具也不会启用。Cota 不另写跨平台替代实现，也不因此宣称已有 Windows 发布包。

Cota 在每轮开始用 Pi 官方 grep/find 工具检查空临时目录；这不是模型发起的业务调用，不追加工具事件。worker 设置官方 `PI_OFFLINE=1`，不在用户请求期间自动下载 rg/fd。依赖由部署方提前安装，例如 macOS `brew install ripgrep fd`，Debian/Ubuntu `apt-get install ripgrep fd-find`。检查失败可从 Debug 的 Skills & Tools 查看；`native_tools.available` 是本轮初始提供的原生工具集合。保存的历史清单不重新探测当前机器。

| Pi 提供 | Cota 提供 |
| --- | --- |
| 原生参数 schema、参数准备和调用循环 | 可信部署配置、每轮不可变环境绑定 |
| read 的分页、截断和图片处理 | none 模式资源目录校验、Skill 内容哈希 |
| write/edit 的文件操作、匹配、diff | 目标工作目录及可追溯的执行结果 |
| grep/find/ls 的搜索、列举和截断；bash/powershell 的命令执行及取消 | 单次命令时间上限、桥接取消传递 |
| 工具自身的 prompt guidelines | 与 Skill 目录、业务 prompt 和 Policy guidance 组合 |

实现使用 Pi 公开的 `createReadToolDefinition` / `createWriteToolDefinition` / `createEditToolDefinition` / `createBashToolDefinition`，以及 `createGrepToolDefinition` / `createFindToolDefinition` / `createLsToolDefinition` / `createPowerShellToolDefinition`。这些定义的 execute 接口可以直接供 Agent Core 调用，不需要 AgentSession。Cota 不复制匹配算法、分页逻辑或 Shell 执行器，也不修改 Pi 源码。后续远端执行需要逐项确认官方接口支持，不能把本地搜索误当成远端搜索。

**machine 是可信部署机器执行，不是沙箱，仅允许用于 personal。** 工作目录只是 cwd，绝对路径、`..`、Shell、环境变量和网络均受部署进程的操作系统权限约束。个人本地和个人云主机使用相同模式。个人使用若不需要机器工具，可显式设 `environment.type: none`。只读环境不能仅靠隐藏 write/edit 实现，因为 bash 同样能修改文件。

`service` 当前拒绝绑定 machine，仍可使用配置允许的业务扩展工具和 Skill 资源读取。工具需自行校验业务权限；deploy 不替代 Application 的身份与会话归属校验。个人 Bot 即使使用 Web/飞书入口，也仍是 personal；对外分享时应改为 service。选择 personal 不会阻止你错误地公开个人执行权限，因此不要把它当成登录控制。

后续 service 可接用户专属环境、群组共享环境或已授权 Client；部署在用户电脑的 Client 不会使托管 Bot 变为 personal。当前尚未提供这些执行端，也不会用每用户子目录冒充隔离。

当前只实现 none 和 machine。旧 `environment.type: host` 和 `deploy: local/host/remote` 不再接受。device、container、readonly 等配置明确报错，不会回退到宿主机。远端设备须有经过认证的执行端，容器须真正约束文件、网络、凭证和进程；这些后端尚未实现。WebSocket 接入本身不会授予浏览器用户本机文件访问权。

Pi 内部的文件修改队列只覆盖单个 worker；不同会话/worker 写同一文件没有事务隔离。machine 不承诺多人文件并发隔离。Skill 的脚本与依赖需由部署方准备；读取 SKILL.md 不等于安装或运行脚本。

部署模式与解析后的环境在每轮绑定；工具执行前重新核对，运行中切换模式或环境会阻止原生调用。所有原生调用同样保存 `tool_started` / `tool_result`；结果保存成功后才允许继续。edit 保存 diff，bash/powershell 保存退出码、耗时、截断状态和可能的完整输出临时路径；模型可见正文单独保留且不再复制完整 Shell 输出。临时输出路径指向宿主机文件，不是持久化附件服务，清理或迁移后不可保证文件仍存在。搜索/列举工具的原生截断与条数限制信息也随结果保存。`deploy`、执行环境和工具可用性保存到本轮 run metadata，可在 Debug 的 Skills & Tools 详情 JSON 中查看。

Shell 命令超时取模型请求和 `timeout_seconds` 上限的较小值；省略时使用环境上限。grep/find/ls 不新增自定义超时机制，取消信号直接交给 Pi；`dialogue.run_timeout_seconds` 仍限制整轮执行。取消通过 AbortSignal 交给 Pi 终止命令进程树，不回滚已经完成的文件写入，不自动重试。

## HTTP 工具

`http_request` 是唯一随 Cota 提供的自定义工具，定义位于 `cota/runtime/pi/http.mjs`，直接符合 Pi `AgentTool` 契约。参数由 TypeBox 声明并由 Pi 校验，Node 执行 HTTP/HTTPS 请求，返回 `content` / `details` / `isError`，不再经过 Python HTTP 工具类。

personal 与 service 均可使用；可用 `tools.allow: [http_request]` 仅开放 HTTP，或 `tools.deny: [http_request]` 关闭它。`tools.allow: []` 关闭自定义工具，但不改变环境决定的 Pi 机器工具与 Skill 读取能力。

HTTP 默认超时 30 秒、上限 60 秒，独立于 Shell 超时配置；响应体超过 256 KiB 会中止并返回错误。只接受公开 HTTP/HTTPS 地址，拒绝 URL 内嵌凭据、私有和保留地址，检查实际连接使用的 DNS 地址，不跟随重定向、不使用环境代理。取消信号直接终止请求。HTTP 非 2xx 与网络错误均以 `isError` 表示，响应正文仅保留在模型可见内容中，details 保存简短状态。响应提供时，额外返回 `headers.content-type` 和 `headers.retry-after`；不返回 Cookie 或其余响应头，也不据此自动重试。

执行前检查权限并保存 `tool_started`，结果保存为 `tool_result` 后才继续模型循环；HTTP 工具不直接依赖 DST 或 Store。

### 业务接入由外围应用负责

Cota 不管理业务 API 密钥、租户权限、业务幂等或服务专属重试。需要认证的接口由外围应用的适配器或独立工具服务接入，使用现有注册接口即可：从可信会话绑定取得调用者，检查业务权限，在真正发请求时注入凭据，只返回必要业务结果。无需把密钥交给模型，也无需为每项业务在 Cota 核心中新增工具。

内置 `http_request.headers` 是模型参数，不是保密配置：参数会进入正常执行记录，Debug 也可能保存完整模型请求。不要把长期密钥放在 Skill、Policy、prompt 或模型填写的 headers 中。HTTP 工具不会自动附加 Cota 的用户身份；单纯代理一个 URL 也不会建立认证。受保护的调用应由外围可信代码完成，不能把模型传入的 user_id 当作调用者身份。

超时、取消、连接中断或响应过大，只表示本次调用未取得完整结果，不保证远端操作未发生。创建订单等写入操作应由业务服务提供幂等键和结果查询；Skill/Policy 可以指导先查结果再决定下一步。Cota 不自动重放工具调用，外围也不应因回复投递失败而重跑整个 Agent。

## Python 工具

实现 `Tool.name`、`description`、`parameters` 和异步 `execute()`，或用 `FunctionTool` 包装已有函数：

```python
from cota.executor.tools.base import FunctionTool

async def lookup_status(order_id):
    return {"order_id": order_id, "status": "processing"}

agent.get_tool_registry().register(FunctionTool(
    name="lookup_status",
    description="查询订单处理状态",
    parameters={
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
    handler=lookup_status,
))
```

此例只返回固定测试数据。真实工具应自行校验业务身份和对象权限。工具可以返回普通业务数据，或使用 Pi 原生 `content` / `details` / `isError` 结果；runtime 保存执行结果并转换为模型内容。`ToolWrapper` 把普通执行异常变成失败结果，取消不会被吞掉。

每轮执行通过 `for_execution(user_id, service_mode)` 创建独立工具视图，避免并发会话互相覆盖用户绑定。需要额外共享状态的自定义工具应明确其并发与清理行为。

## 权限与可用性

`ToolRegistry.get_allowed_tools()` 同时检查 `enabled` 与 `ToolPolicy`。普通工具的 deny 优先于 allow；省略 allow 表示不额外收窄。内置 `http_request` 与应用注册的自定义工具均受 allow/deny 控制。Pi 八个基础工具由 `environment` 决定，不受扩展工具的 allow/deny 控制；在这两个列表中填写基础工具名称会报配置错误。

未知分组在配置读取时立即报错。应用工具可以在 Agent 加载后注册，因此具体工具名称在每轮创建 runtime 前校验；拼写错误和未注册的名称会明确报错，尚未调用模型。应用也可以在完成注册后主动调用 `agent.get_tool_registry().validate()` 做启动检查。注册名称只接受字母、数字、下划线、连字符，同名覆盖和占用 Pi/HTTP 保留名称立即拒绝；独立工具进程批量注册失败时不会留下部分工具。

每轮开始在日志输出可用工具及缺失原因；Debug 的 Skills & Tools 在已有 `discovery.tools` 中统一显示来源（pi / cota / application）、可用状态与原因。执行环境仍在同一份运行元数据中。这是初始诊断清单，不参与授权和 DST 恢复；权限运行中改变后，具体模型请求实际拿到的工具以 Model Requests 为准，不新增 Event。

读取某个 Skill 不会解锁工具。Policy guidance 不能授权新能力。runtime 在每次准备请求以及实际执行前重新检查许可，撤销权限后即使模型仍提出旧调用，也会被阻止。

模型需要补充信息时直接回复问题，最终输出由 Cota 保存为 `bot_utter`，再经持久化 Channel 投递。用户记忆、定时服务和 MCP 客户端保留为后端设施，默认不向模型注册相关工具。

## 独立工具进程

部署方可以启动准备好的工具服务，并注册到同一 ToolRegistry：

```python
from cota.executor.tool_process import SubprocessToolClient

client = SubprocessToolClient(
    ["/opt/my-tool/.venv/bin/python", "/opt/my-tool/server.py"],
    cwd="/opt/my-tool",
)
await agent.get_tool_registry().connect_process(client)
```

工具进程使用 Cota 的 `initialize` / `execute` / `shutdown` JSON-lines 协议，不是 MCP。依赖环境和启动命令由部署方准备；Cota 不因阅读 Skill 自动安装依赖或启动脚本。注册时不允许覆盖已有工具；`read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`powershell` 和 `http_request` 是保留名称，不论是否加载 Skill，业务扩展都不能占用它们。远程 schema 仍受正常工具权限控制。

同一进程的 RPC 顺序执行。超时、取消或协议故障后关闭进程，不自动重放可能已有副作用的调用；重新连接需显式创建客户端。Registry 清理会关闭它拥有的进程。工具进程本身不等于沙箱或用户权限边界。

实现入口：`cota/executor/environment.py`、`cota/runtime/pi/tools.mjs`、`cota/executor/tools/base.py`、`cota/executor/tools/registry.py`、`cota/executor/tools/proxy.py`、`cota/executor/tool_process.py`。

相关文档：[MCP](../components/mcp.md) · [Agent 配置](../configuration/agent.md) · [执行流程](execution-flow.md) · [Skills](../skills/overview.md)

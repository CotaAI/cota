# agent.yml

`agent.yml` 定义 Bot 的业务行为。`Agent.load_from_path()` 先调用严格 validator，再与默认值合并；未知顶层字段或未知 dialogue 字段直接报错。

## 最小示例

```yaml
system:
  name: Support Bot
  description: 你是客服助手，依据已有资料回答，不编造查询结果。
dialogue:
  runtime: pi
  llm: default
  max_tokens: 2000
  max_iterations: 12
  prompt: |
    {{task_description}}
    用户偏好：{{user_context_text}}
    按需阅读可用 Skill。缺少必要信息时向用户追问。
tools:
  allow: [web_fetch]
  deny: []
policy:
  type: all
```

模型 `default` 在 `endpoints.yml` 定义。配置允许工具不会替代真实服务权限；不配置 Skill 也可以进行纯对话。

## system 与 dialogue

| 字段 | 默认 / 约束 |
| --- | --- |
| `system.name` | 可选文本，Bot 名称 |
| `system.description` | 可选文本；缺省使用个人助理描述 |
| `dialogue.runtime` | `pi`；只支持 Pi |
| `dialogue.llm` | 省略时用 endpoints 中第一个模型 |
| `dialogue.mode` | `direct` 或 `group`，默认 `direct` |
| `dialogue.response` | `passive` 或 `proactive`，默认 `passive` |
| `dialogue.prompt` | 文本模板，省略时使用默认业务指引 |
| `dialogue.max_tokens` | 每次主模型请求上限，默认 500，正整数 |
| `dialogue.max_iterations` | Processor 创建 runtime 时默认 30，正整数 |
| `dialogue.run_timeout_seconds` | 整轮 Pi bridge 超时，默认 300，正有限数值 |
| `dialogue.compaction.trigger_tokens` | 工作上下文触发阈值，默认 64000；实际取它与 `context_window-reserve_tokens` 的较小值。整数且至少为 2，不修改供应商模型真实容量 |
| `dialogue.compaction.reserve_tokens` | 上下文预留 token；默认取输出上限与 `min(16384, context_window/4)` 中较大者，必须覆盖 `max_tokens` 且小于模型容量 |
| `dialogue.compaction.keep_recent_tokens` | Pi 切分时尽量保留的最近 token；默认 `min(12000, 实际触发阈值/2)` 向下取整，须小于实际触发阈值；安全切分需要时可减少保留量 |
| `dialogue.compaction.max_request_bytes` | 序列化工作上下文（含工具定义、图片 Base64 与待注入图片的估计体积）的字节预算，默认 32 MiB（33554432），正整数且不超过 64 MiB；超出时也复用 Pi 压缩 |
| `dialogue.compaction.max_images` | 有效模型上下文中的图片数量预算，默认 8，正整数 |
| `dialogue.compaction.max_image_bytes` | 有效上下文中的图片解码后总字节预算，默认 16 MiB（16777216），正整数；与 Base64 后的整体请求预算分别计算 |
| `dialogue.pi_node` | 可选 Node 路径或可执行文件名称 |

工作预算包含 system、工具声明、本次临时指导及工作历史。模型支持 1M token 不代表应每次携带接近 1M 的历史；例如可配置：

```yaml
dialogue:
  compaction:
    trigger_tokens: 64000
    keep_recent_tokens: 12000
```

超过 token 或序列化字节预算时，运行适配层调用 Pi 的公共判断、切分和摘要组件。单条当前输入、工具批次或固定指导过大时会明确报错。原生主模型明确报告上下文溢出时，在剩余模型决策次数允许且非收尾阶段下，最多压缩并续接一次；不会重放已执行工具。Python custom/RAG 适配器仍沿用自身错误路径。

`mode` 和 `response` 的行为需结合 [群聊](../deployment/group.md) 与 Application 使用。`use_proxy_user`、`max_proxy_step`、`proxy_prompt` 和顶层 `user_proxy.description` 仍被配置校验接受，但当前带输入标识的 Processor 路径明确拒绝启用 proxy 模拟，不作为可部署对话方案。

Token、整体序列化字节、图片数量和图片字节预算分别检查。图片 Base64 不当作文本 token，但会占用传输体积。任一预算超限都复用 Pi 摘要，并降低最近 token 保留目标，直到完整的最近工具调用/结果批次能放下。旧 Events 与图片不删除。单个最近批次仍过大时明确失败，需读取较小/较少图片，或在确认服务限制后调整预算；不会静默拆开同批次多图。32 MiB 是 Cota 的运行预算，不是供应商声明的请求上限。

压缩依据通用预算与消息顺序，不推断图片“已审阅”或“旧版本”。Pi 摘要读取文本证据，无法凭空补做视觉审校；需要时 Agent 重新读取对应资产。近期完整工具批次受到保护，但更早批次的图片可能移出模型上下文，多图比较应一次读取所需参考图与目标图。请求体引用/缓存与减少模型视觉上下文是不同问题。

## Prompt 变量

允许的变量是 `task_description`、`agent_description`、`user_context_text`、`session_summary`、`latest_user_query`、`compressed_history`、`history_messages`、`knowledge`。写法为 `{{变量名}}`，未知变量报错。

`task_description` 和 `agent_description` 来自 Bot 描述；用户记忆取自 DST 已记录状态。历史消息本身已进入模型上下文，模板中重复插入完整 history 会增加长度，通常不需要。

## deploy 与 environment

`deploy` 使用 `personal` 或 `service`，省略时为 `personal`。两者行为相同，均默认 machine 环境。不需要原生工具的 Bot 显式设 `environment: {type: none}`。对外提供服务时通过 sandbox 隔离执行。

省略 deploy 即使用默认配置，等价于：

```yaml
deploy: personal
environment:
  type: machine
  workspace: ./files
  timeout_seconds: 60
```

`workspace` 相对 Bot 目录解析，默认 `files`，首次执行才创建；SDK 直接 `Agent(deploy='personal')` 时相对创建 Agent 时的 cwd。`timeout_seconds` 默认 60，为正有限数值，限制单次 bash/powershell。工作目录是起始位置，不是沙箱。machine 使用部署账号的文件、进程与网络权限。不需要机器工具时可显式使用 `environment: {type: none}`。

对外提供服务时，通过 `cota/platform/sandbox.py` 的 Sandbox（DockerSandbox / GVisorSandbox）隔离每个会话的执行环境，而不是依赖框架层面的能力限制。

旧 `environment.type: host`、`deploy: local/host/remote` 不再支持。`deploy` 和实际执行环境记录到 run metadata，不增加对话 Event。详见 [工具与执行环境](../concepts/tool-adapters.md)。

`environment.shell` 可选 `auto`（默认）、`bash`、`powershell` 或 `both`。auto 提供可用 Shell；显式指定但不可用时在主 Agent 模型循环开始前报错。Pi 1.4.0 的 PowerShell 仅支持 Windows。grep/find 分别需要预装 rg/fd（或 fdfind），缺失时省略并记录原因，不在运行时下载。

`tools.allow/deny` 只控制业务扩展；八个 Pi 原生工具由环境与依赖可用性决定，不要把它们填写在这些列表中。

## tools、policy 与 knowledge

`tools.allow` / `deny` 是工具名称或分组名称列表。内置 `web_fetch` 使用 Pi 标准工具定义；machine 环境还可配置 `send_files`，用于交付工作区文件到当前会话，见 [附件](../concepts/attachments.md)。`image_generate` 和 `image_understand` 在 endpoints 中配置了对应端点时自动可用，见 [图片工具](../concepts/tool-adapters.md#图片生成与图片理解工具)。`group:network` 只包含 web_fetch，`group:image` 包含 image_generate 和 image_understand，`group:all` 可用于所有当前可用工具。省略 allow 表示允许当前启用的自定义工具，空 allow 不提供自定义工具；deny 优先。Pi 原生工具与 Skill 资源读取由 environment 决定。

未知分组在加载配置时拒绝；具体名称在应用完成工具注册后的运行入口校验，未注册或拼错的工具会在调用模型前报错。应用可在注册结束后调用 `agent.get_tool_registry().validate()` 提前检查。业务 API 凭据、身份鉴权与幂等由外围适配器或工具服务负责，Cota 不新增凭据管理配置，见 [Tool 适配](../concepts/tool-adapters.md)。

Policy 不改变工具权限。`policy.type` 默认 `all`，其他策略的 options、训练和产物配置见 [Policy 配置](policy.md)。业务案例写入 `policy/`，不塞进 `agent.yml` 的 dialogue 字段。

可选 `knowledge` 是列表，当前支持 `type: llm`，并指定 `llm`、可选 `prompt`、`max_tokens`、`temperature`。知识内容通过 `{{knowledge}}` 等模板调用参与本轮准备；它不是额外 Agent。

可选 `channels` 为部署默认值，推荐把平台凭证放在 endpoints。模型可用工具由当前配置与执行环境决定；群聊不加载成员个人记忆，详见 [Tool 适配](../concepts/tool-adapters.md)。

实现入口：`cota/config.py`、`cota/constant.py`、`cota/agent.py`、`cota/processor.py`。

相关文档：[Endpoints 配置](endpoints.md) · [Agent](../concepts/agent.md) · [执行流程](../concepts/execution-flow.md) · [Skill Policy](../concepts/skill-policy.md)

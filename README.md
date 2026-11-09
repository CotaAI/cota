# Cota

**Bot 开发与部署平台：定义业务能力与规则，交付可使用、可追踪、可持续改进的机器人。**

Cota 帮助不需要掌握完整 Agent 工程体系的开发者，把业务知识、工具和对话规则组织为一个 Bot，供自己使用或分享给他人。个人助手、客服、群聊助手是同一框架上的不同应用场景。

交付单位是 **Bot**：除了 Skill，还包含角色与行为配置、工具权限、Policy、模型服务和存储配置。创作者可以维护一个服务并分享聊天入口，也可以分享 Bot 文件夹，由使用者自行部署。Skill 是其中可复用的业务能力说明，单独分享 Skill 不会交付运行环境、工具权限和持续服务。

## 核心分工

```text
用户 / 外围应用 / 可选聊天页面
  → Channel + Application：接入、授权适配、去重、顺序和投递
  → Processor + DST / Store：记录输入、恢复状态、保存执行事实
  → Pi Agent Core：模型调用、工具调用、多步循环
       ↕ Cota：模型适配、Policy 指导、工具能力与持久化确认
```

- **Skill** 定义业务能力和 SOP；模型选择、读取和组合它们，资源加载复用 Pi 的实现。
- **Tool** 提供真实能力。唯一内置自定义工具是 Node 中的 `http_request`；机器操作使用 Pi 官方八个原生工具，按执行环境与可用依赖提供。Skill 文本和 Policy 示例不自动注册工具，也不授予权限。
- **Trace** 从事件和运行记录呈现实际发生了什么；DST 通过事件恢复状态，Store 保存事件和快照。
- **Policy** 来自业务流程标注，每次模型请求前结合当前上下文提供指导，改善 Skill 选择、组合、异常处理与回复。
- **Eval** 随 Bot 交付 `policy/eval` 对话验证，用 LLM 逐条评判回复，保存执行证据、报告与版本对比；见[评测指南](docs/src/development/evaluation.md)。
- **应用层** 协调会话和回复。已有应用管理自己的身份与群成员；没有现成前端时，可以启用独立的 Web 聊天应用。

使用官方 TypeScript Pi Agent Core，不接入 Pi AgentSession。会话历史与上下文恢复由 Cota 管理，不依赖 Pi 的本地会话文件。

## 从当前源码开始

本版 **2.0.0 以 GitHub 源码发布**，不附加大型安装包，也不发布 PyPI。源码开发需要 Python 3.12+、Node.js 22.19+ 和 npm：

```bash
# 在仓库根目录，激活你的 Python 虚拟环境后
python -m pip install -e '.[dev]'
npm ci --prefix cota/runtime/pi
cota init
```

`cota init` 在当前目录创建 `cota_projects/weather`，不会覆盖已有 Bot。
编辑所选 Bot 的 `endpoints.yml`，直接填写模型服务配置：

```yaml
llms:
  default:
    type: openai
    key: "填写模型服务密钥"
    apibase: "填写兼容 Chat Completions 的 API 地址"
    model: "填写模型名称"
```

不需要 `COTA_API_KEY`。保留模板中的 SQLite 存储配置，然后启动：

```bash
cota shell --config cota_projects/weather --debug
# 或使用浏览器聊天入口
cota run --config cota_projects/weather --chat-app --host 127.0.0.1 --port 5005
```

聊天页面在 `http://127.0.0.1:5005/chat/`；shell 的 Debug 页面地址由终端输出。
唯一分发的示例 `weather` 组合当前天气与预报、活动查询、出行规划三个 Skill，并附带30个对话评测案例。

在 `agent.yml` 中用 `deploy: personal` 表示自己使用（本机或个人云服务器），用 `deploy: service` 表示对外提供服务。模板及省略配置时均为 service，不开放机器原生文件和 Shell。personal 默认复用 Pi 工具操作部署机器，起始目录为 Bot 下的 `files/`；它不是沙箱。模式与执行环境配置见 [Agent 配置](docs/src/configuration/agent.md)。

保留将固定版本 Node/Pi 构建进平台 wheel 的能力，用于本地或 CI 安装验证；生成物不提交 Git，也不随本版上传。模型凭据、外部工具及 Bot 特有依赖由部署者配置。安装方式与构建说明见 [安装说明](docs/src/installation/install.md)，本版变更见 [2.0.0 发布说明](docs/releases/2.0.0.md)。

## 像编写对话一样标注业务流程

```yaml
policies:
  - name: 天气查询失败时说明限制
    steps:
      - user: 北京现在多少度？
      - bot:
          - thought: 需要实时数据，使用天气能力。
          - skills: [weather]
          - result: 主服务和备用服务都没有返回有效天气数据。
          - thought: 明确说明暂时无法确认，不猜测温度。
          - reply: 暂时未能查询到天气，我还不能确认当前温度。
```

保存到 Bot 的 `policy/`。`thought` 是人工编写的业务判断，`result` 是案例结果条件；它们都不是真实执行事实或模型隐藏推理。默认 `all` 策略直接加载案例；BM25、Embedding、模型判断等策略先用 `cota train --config BOT` 构建产物，再由运行时加载。修改文件后重新加载 Agent，不自动热更新。

真实对话也可通过 `cota annotate export` 导出，人工改写后 `annotate import` 校验成相同格式；不会把标注写回执行事件。

## 验证 Bot 的实际回答

配置好 weather 的模型后，在 Bot 目录直接执行：

```bash
cd cota_projects/weather
cota eval
```

默认读取 `policy/eval/`，优先用 `llms.evaluator` 评判，未配置时用 `llms.default`。终端显示案例、轮次、执行/评判阶段和等待进度；结果保存在 `workspace/evaluations/<run_id>/`，包含报告、结构化评分和执行证据。`--debug` 额外保存被测 Bot 的模型请求，不是开启进度的开关。

用 `cota eval judge` 重评已有 Trace，用 `cota eval compare` 对比版本。评委也可能误判，关键项应核对实际回复和工具正文。命令、文件格式和对比规则见[评测指南](docs/src/development/evaluation.md)。

## 当前交付能力

| 场景 | 当前入口 |
| --- | --- |
| 本地个人 Bot | `cota shell`、SQLite、Pi 原生机器工具 |
| 网页或已有应用中的聊天 | Web Channel 的 HTTP + WebSocket，外围身份授权，统一 Application |
| 没有现成聊天界面 | `cota run --chat-app`，访客身份、会话列表、单聊/群聊、邀请 |
| 飞书单聊与群聊 | 官方 SDK 接入，事件去重与持久化回复投递 |
| 群聊中的 Bot | 普通消息先保存；被 @ 回复，或启用有节流和失效检查的主动参与判断 |
| 交付 Bot 文件夹 | 配置、Skill、Policy、可选训练产物及依赖说明；接收方独立配置和启动 |

当前执行协调以单进程为边界，工具进程不等于安全 sandbox。自动 RSI、完整自包含 Bot 安装包和分布式执行尚未实现，见 [能力边界与规划](docs/src/concepts/roadmap.md)。

## 文档与开发

- [手册入口](docs/src/introduction.md) · [快速开始](docs/src/tutorial/quick_start.md)
- [定位与架构](docs/src/concepts/raas_architecture.md) · [模块地图](docs/src/concepts/modules.md) · [执行流程](docs/src/concepts/execution-flow.md)
- [Skill、Trace 与 Policy](docs/src/concepts/skill-policy.md) · [Policy 训练与推理](docs/src/concepts/trainable-policy.md)
- [配置参考](docs/src/configuration/overview.md) · [Debug](docs/src/deployment/debug.md)
- [应用接入](docs/src/deployment/application.md) · [部署与分享](docs/src/deployment/sharing.md)
- [示例 Bot](bots/README.md) · [测试指南](tests/README.md)

```bash
python scripts/check.py --coverage
```

检查 Python/JavaScript/Shell 语法、Ruff、Python 与 JavaScript 回归并生成覆盖率。测试使用可控模型响应，不需要模型密钥；真实模型效果仍需业务评测。发布与测试工作流见 `.github/workflows/`。

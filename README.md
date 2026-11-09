# Cota

**Bot 开发与部署平台，让懂业务的开发者更容易做出自己的机器人，并交付给自己或他人使用。**

用 **Skill** 定义业务能力，用 **Policy** 教 Bot 如何处理业务，再通过聊天入口或 Bot 文件夹交付。Cota 提供执行、会话管理、调试和评测能力，让你可以围绕业务持续改进机器人。

Cota 的交付单位是 **Bot**，包含角色、Skill、Policy、工具权限、部署配置和验证案例。个人助手、客服、群聊助手是它支持的应用场景。

[快速开始](#快速开始) · [示例 Bot](bots/weather/README.md) · [完整文档](docs/src/introduction.md) · [2.0 更新](docs/releases/2.0.0.md)

## Cota 适合你吗？

如果你已经知道机器人要服务什么业务，希望通过配置、Skill 和对话案例把它做出来，并愿意维护它的运行环境，Cota 适合你。

| 你想做什么 | Cota 提供什么 |
| --- | --- |
| 做一个自己长期使用的个人助手 | 在自己的电脑或云主机部署，保留对话与个人记忆，按配置使用部署机器上的工具 |
| 把业务知识和接口做成客服或业务助手 | 定义业务 Skill，用对话案例指导查询、异常处理和回复，接入已有网页或应用 |
| 给团队或社群提供一个群聊 Bot | 接入飞书或 Web 群聊，被 @ 时回应，也可启用主动参与判断 |
| 把做好的 Bot 分享给别人 | 维护一个服务并分享聊天入口，或交付 Bot 文件夹供对方独立部署 |
| 持续改进 Bot 的业务表现 | 查看实际执行记录，修改业务案例，用同一份验证集评测并对比版本 |

**使用门槛：**需要能够编辑 YAML/Markdown、配置模型服务，并启动 Python 应用。业务能力主要写在 Bot 文件中，执行与会话协调由框架提供。

**部署方式：**Cota 是需要自行部署的开源项目。创作者分享服务入口时负责服务维护；分享文件夹时由接收方负责部署。当前提供文件配置与命令行工作流，执行协调以单进程为边界。托管平台、可视化拖拽搭建和多实例执行不在当前交付范围内。

## Cota 2.0 的核心能力

| 能力 | 对 Bot 开发者的价值 |
| --- | --- |
| **Skill 组合与工具执行** | 将业务能力拆成独立 Skill，由模型按任务选择和组合。复用官方 Pi 的执行循环、Skill 加载和原生工具，通过 `http_request` 调用业务接口 |
| **对话式业务指导 Policy** | 像编写示范对话一样描述正确做法：何时使用哪个 Skill、遇到不同结果如何继续、最终怎么回答。运营人员可以参与业务标注 |
| **Policy 训练与推理** | 简单 Bot 可直接加载案例；案例增多后，可使用 BM25、Embedding 或模型策略准备训练产物，在每次模型请求前选取适用的业务指导 |
| **执行记录与 Debug** | 保存真实对话、工具调用和结果，追踪 Skill 的读取。调试页面集中查看事件、当前状态和模型请求，帮助定位错误发生在哪一环 |
| **对话评测与版本对比** | 用自然语言写回复要求，`cota eval` 通过 LLM 逐项评判，输出报告和结构化执行证据；支持重评已有记录、比较多次评测结果 |
| **会话与应用接入** | 输入先保存，再按会话排队执行；区分会话历史与个人记忆，处理去重和跨会话并发。Web 支持断线补取历史，飞书支持持久化回复重试 |
| **单聊、群聊与配套页面** | 提供命令行、Web HTTP/WebSocket 和飞书入口；可选 Web 聊天应用包含会话列表、历史分页、未读和阅读位置 |

这些能力围绕同一个交付单位工作：**Bot**。

## 一个 Bot 包含什么？

```text
my-bot/
├── agent.yml                 # 角色、行为、部署模式、工具权限与 Policy 策略
├── endpoints.yml             # 模型服务、渠道和存储配置
├── skills/                   # 业务能力说明、SOP 与所需资源
└── policy/
    ├── data.yml              # 业务指导案例：教 Bot 怎样处理问题
    └── eval/data.yml         # 验证案例：检查 Bot 是否做到了
```

这个目录可以跟随业务一起迭代，也可以作为交付物分享。接收方安装 Cota、配置自己的模型凭据和业务依赖，就能启动 Bot。分享服务时，使用者通过聊天入口访问，由服务维护者管理配置与更新。具体责任与准备工作见 [部署与分享](docs/src/deployment/sharing.md)。

### 用业务案例指导决策

例如，天气服务不可用时，希望 Bot 说明情况，而不是编造天气。在 `policy/data.yml` 中写一段示范：

```yaml
policies:
  - name: 天气查询失败时说明情况
    steps:
      - user: 北京现在多少度？
      - bot:
          - thought: 用户需要实时气温，使用天气查询能力。
          - skills: [weather]
          - result: 主服务与备用服务都没有返回有效天气数据。
          - thought: 当前无法确认气温，说明暂时查不到，不猜测数值。
          - reply: 暂时没查到北京的气温，稍后再试一下吧。
```

`thought` 是标注人员写下的业务判断，`result` 描述这个案例遇到的结果。Cota 在模型请求前结合当前对话与执行进展，提供适用的 Policy 指导，影响后续 Skill 选择、结果处理与回复。模型仍依据本次真实数据执行；案例中的结果不是实时事实。

你可以直接编写案例，也可以用 `cota annotate export` 导出真实对话草稿，人工修改后通过 `annotate import` 校验。标注方式见 [Skill、Trace 与 Policy](docs/src/concepts/skill-policy.md)。

### 用验证案例检查改进效果

在 `policy/eval/data.yml` 中，用相近的对话格式写下用户问题和回复要求：

```yaml
policies:
  - name: 缺少查询城市
    steps:
      - user: 帮我查一下天气
      - bot:
          reply-review:
            - 询问用户要查询的城市。
            - 不擅自选择城市，也不编造天气数据。
```

在 Bot 目录执行 `cota eval`，即可查看进度、逐项评分与执行证据。评测优先使用 `llms.evaluator`，未配置时使用默认模型；评测要求不会提供给被测 Bot。

业务改进可以按以下流程进行：

```text
查看真实执行记录 → 修改 Skill / Policy → 按需训练 → 运行评测 → 比较结果 → 部署新版本
```

`cota train` 为训练型 Policy 准备索引等产物；`cota eval judge` 可重新评判已有执行记录，`cota eval compare` 可比较多次评测。用法见 [Policy 训练](docs/src/concepts/trainable-policy.md) 与 [评测指南](docs/src/development/evaluation.md)。

## 快速开始

### 1. 安装

需要 Python 3.12+。从 PyPI 安装已发布版本：

```bash
python -m pip install -U cota
```

使用飞书时安装 `cota[feishu]`。带内置运行时的平台 wheel 包含固定版本 Node/Pi，无需额外安装 Node.js 或 npm。平台要求见 [安装说明](docs/src/installation/install.md)。

<details>
<summary>从源码开发或体验仓库中的最新代码</summary>

另外准备 Node.js 22.19+ 和 npm；固定 Node 版本见 `.node-version`。

```bash
git clone https://github.com/CotaAI/cota.git
cd cota
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci --prefix cota/runtime/pi
```

</details>

### 2. 创建示例并配置模型

```bash
cota init
cd cota_projects/weather
```

`cota init` 创建示例目录，保留已有的同名 Bot。编辑 `endpoints.yml` 中的模型配置，保留模板中的 SQLite 存储配置：

```yaml
llms:
  default:
    type: openai
    key: "填写模型服务密钥"
    apibase: "填写兼容 Chat Completions 的 API 地址"
    model: "填写支持工具调用的模型名称"
```

### 3. 对话、调试和评测

在 Bot 目录执行：

```bash
cota shell --debug       # 终端对话，终端会输出 Debug 页面地址
cota eval                # 运行 Bot 自带的验证集
```

也可以启动浏览器聊天页面：

```bash
cota run --chat-app --host 127.0.0.1 --port 5005
```

打开 `http://127.0.0.1:5005/chat/` 即可使用。本地验证后，可按 [部署指南](docs/src/deployment/guide.md) 配置对外服务入口。

### weather 示例能验证什么？

它组合了天气查询、活动查询和出行规划三个 Skill。你可以问：

> 杭州，两大一小，今天想找室内亲子活动，门票总预算三百。
>
> 预算改成一百，其他条件不变。

示例附带 **30 个对话评测案例**，覆盖能力选择、多轮条件变更、预算约束和异常处理。天气查询使用外部接口，活动查询使用随示例提供的活动目录，便于复现验证。详情见 [weather 示例](bots/weather/README.md)。

## 运行与交付的边界

- **自用与服务分开配置。**`deploy: personal` 用于自己的电脑或云主机；`deploy: service` 用于对外提供服务，默认不开放部署机器的原生文件与 Shell。机器工具的工作目录不构成安全沙箱。
- **身份与业务授权属于外围应用。**Cota 接收已验证的用户和会话标识，负责执行与记录；已有登录系统和群成员体系通过接入契约对接。
- **Policy 提供指导，评测提供证据。**Policy 不保证模型严格遵循每个步骤；LLM 评委也可能误判，关键业务结果需要复核。
- **自动 RSI 是后续方向。**当前已具备记录、标注、训练与评测基础；自动生成优化版本、自动验证并应用尚未实现。完整自包含 Bot 安装包、分布式执行也在后续范围内。

详细配置与限制见 [Agent 配置](docs/src/configuration/agent.md)、[应用接入](docs/src/deployment/application.md) 和 [能力边界与规划](docs/src/concepts/roadmap.md)。

## 技术分工与开发

**Pi 负责 Agent 的模型—工具执行循环；Cota 负责 Bot 的业务指导、状态持久化、应用接入、交付与验证。**

Cota 使用官方 TypeScript Pi Agent Core。会话状态由 DST 根据事件恢复，Store 保存事件与快照，Trace 呈现执行证据。个人 Bot 和多人服务使用同一套状态语义，按部署需求选择持久化后端。

- [定位与架构](docs/src/concepts/raas_architecture.md) · [模块地图](docs/src/concepts/modules.md) · [执行流程](docs/src/concepts/execution-flow.md)
- [配置参考](docs/src/configuration/overview.md) · [Debug](docs/src/deployment/debug.md) · [Web 接入](docs/src/deployment/api.md)
- [测试指南](tests/README.md) · [发布流程](docs/releases/README.md)

在源码开发环境中运行完整检查：

```bash
python scripts/check.py --coverage
```

检查语法、静态规则、Python/JavaScript 回归与覆盖率。框架测试使用可控模型响应；业务效果使用自己的验证集和模型服务评测。

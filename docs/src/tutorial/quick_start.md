# 快速开始

先按 [安装说明](../installation/install.md) 准备当前源码或对应发布包。下面从官方 weather 模板开始。

## 1. 初始化与配置

```bash
cota init
```

编辑 `cota_projects/weather/endpoints.yml`：

```yaml
base_store:
  type: sql
  dialect: sqlite
  db: workspace/sessions.db
llms:
  default:
    type: openai
    key: "填写模型服务密钥"
    apibase: "填写兼容 Chat Completions 的 API 地址"
    model: "填写支持工具调用的模型名称"
```

这些字段直接从文件读取，不需要 export COTA_API_KEY，也不使用 `${...}` 占位替换。
模型调用会使用你配置的服务；weather 的 HTTP 工具还需要能访问相应天气 API。

## 2. 在 shell 验证

```bash
cota shell --config cota_projects/weather --debug
```

依次尝试“帮我查天气”“北京”“再比较一下上海”，检查追问、Skill 读取、真实查询和回复。
当服务没有返回数据时，Bot 应明确说明不能确认，不能抄写 Policy 案例里的天气数值。
输入 `/stop` 退出。

终端会输出本次会话的本地只读 Debug 页面地址，可以查看 Events、Skills、Model Requests 和 DST。
完整 prompt 在 Model Requests 的 request 中；具体工具参数、结果在相应事件 JSON 中。详见 [Debug](../deployment/debug.md)。

shell 每次启动创建新会话，不自动接续上一会话；原事件仍留在 SQLite。
跨重启续接需要使用保持同一个 session_id 的应用/API 客户端。

## 3. 批量评测

在新终端进入配置好的 Bot 目录：

```bash
cd cota_projects/weather
cota eval
```

模板包含30个案例、43轮输入、94条评测要求，覆盖天气预报、活动筛选、多轮条件变化和回答表达。无需额外启动活动服务。评委默认复用 llms.default，也可在 endpoints.yml 配置 llms.evaluator 自动优先使用。

终端会显示每个案例、轮次和执行/评判阶段，等待时每15秒提示一次。结束后查看输出路径中的 report.md；结构化结果在 results.json，逐轮证据在 traces/。`cota eval --debug` 额外保存 Bot 模型请求，普通评测也有进度和完整的业务执行记录。

weather 支持当前天气以及明天、周末等16天内逐日预报。活动列表是随模板提供的固定虚构数据，使用正常业务名称测试真实需求下的选择与回复；正式业务部署应替换为真实数据。Bot 回答以建议、费用和必要依据为主，不向用户汇报内部工具选择或测试标签。更多说明见源码中的 `bots/weather/README.md` 和[评测指南](../development/evaluation.md)。

## 4. 启用聊天页面

```bash
cota run --config cota_projects/weather --chat-app --host 127.0.0.1 --port 5005
```

打开 `http://127.0.0.1:5005/chat/`，创建访客身份和会话。
不加 `--chat-app` 时提供 Web 通道 API，不提供默认聊天页面。
这只是本地监听；要分享给其他人，阅读 [交付与分享](../deployment/sharing.md)。

## 5. 理解和修改文件

```text
weather/
├── agent.yml
├── endpoints.yml
├── skills/
│   ├── weather/SKILL.md
│   ├── activity-search/SKILL.md
│   ├── activity-search/activities.json
│   └── outing-plan/SKILL.md
├── policy/data.yml
├── policy/eval/data.yml
└── workspace/                 # 运行时生成，不作为 Bot 定义分享
```

- agent.yml：角色、对话场景、模型引用、工具范围、Policy 方法。
- endpoints.yml：实际模型服务、Store 和渠道部署凭据。
- SKILL.md：天气查询、活动查询和出行规划的 SOP；Pi 发现目录，模型按需读取。
- policy/data.yml：期望的业务对话流程，用 thought、skills、result、reply 指导选择和处理。

`policy/eval/data.yml`：给评委的对话验证要求，不参与 Policy 加载或训练，也不注入被测 Bot 的 prompt。

修改 Policy 后重新加载 Bot。默认 all 无需训练；切换 BM25 等训练型方法后先运行：

```bash
cota train --config cota_projects/weather
cota train --config cota_projects/weather --check
```

init 不升级现有 Bot，不复制运行 workspace、数据库、`.cota` 或日志。更新已有示例时，对照模板合并 agent.yml、skills/、policy/ 和 README，保留自己的 endpoints.yml、业务修改与运行数据；使用训练型 Policy 时重新 train。手动分享已使用的目录前，还需要清除自己填写的凭据。

接着阅读 [天气实践](best_practices/practice_1.md)、[Policy 标注](../concepts/skill-policy.md) 和 [Agent 配置](../configuration/agent.md)。

# Cota Bot 示例

官方仅分发 weather 模板，通过当前 Pi Agent Core 执行链路验证。

weather 显式使用 `deploy: service`，可以在 shell 验证或通过服务入口分享。自用且需要操作部署机器时，改为 `deploy: personal`；默认工作目录是 Bot 下的 `files/`。本机和个人云服务器均属于 personal，用户隔离执行环境与客户端执行端尚未实现。

| Bot | 用途 | 工具与数据 |
| --- | --- | --- |
| `weather` | 当前天气与预报、活动查询、出行规划三个 Skill；业务分支、多轮变化与对话评测 | 真实天气 HTTP + Skill 附带活动 JSON，SQLite |

## 使用

执行 `cota init` 创建模板，再编辑 weather 的 `endpoints.yml`：

```yaml
llms:
  default:
    type: openai
    key: "填写你的模型服务密钥"
    apibase: "填写你的模型服务 API 地址"
    model: "填写你的模型名称"
```

```bash
cota shell --config cota_projects/weather
```

模型服务需支持 OpenAI 兼容 Chat Completions 接口，使用工具的 Bot 需要模型支持工具调用。
源码开发环境先按项目 README 准备 Python 和 Pi 依赖，然后在仓库根目录运行 `cota shell --config ./bots/weather`。

官方模板仅在仓库根目录 `bots/` 维护；构建 wheel 时自动收录到包内 `cota/_templates/bots/`。源码或 editable 安装从仓库读取模板，pip 安装从包内读取模板，均不依赖执行命令时的工作目录。用户通过 `cota init` 创建的 Bot 仍位于当前目录下的 `cota_projects/`。
`cota init` 只复制有效模板，遇到同名目录会跳过，保护已有修改。它不会自动升级或删除以前生成的 Bot。

weather 的活动 JSON 是固定虚构测试数据，以正常业务名称和字段供模型使用，测试说明留在开发文档中。天气来自真实 HTTP 查询，支持当前天气及16天内逐日预报。示例不额外启动活动服务；正式部署前需替换为真实活动来源。回答规范、案例与能力范围见 [weather README](weather/README.md)。

更新已有 weather 副本时，对照模板合并 agent.yml、skills/、policy/ 和 README；保留自己的 endpoints.yml、业务修改及 workspace/.cota 运行数据。训练型 Policy 在更新案例后重新 train，再加载 Bot。

## 目录约定

- `agent.yml`：Bot 定位、模型引用、Pi 设置和工具权限。
- `endpoints.yml`：模型服务与 Store。直接填写 key/model/apibase，不读取环境变量；缺失或为空时会提示需要填写的字段。
- `skills/<name>/SKILL.md`：可选操作指引，只引用已注册工具。不是独立执行器。
- `policy/data.yml`：可选业务案例，为 Pi 提供指导，不是另一个执行循环。
- `policy/eval/data.yml`：可选对话验证集，由 LLM Judge 评分，不参与 Policy 训练；weather 已附带。
- `README.md`：运行方式、测试场景和依赖。
- `workspace/`：运行时生成的 SQLite、日志等，不应提交或放进分享包。SQLite 相对路径以 Bot 目录为基准。
- `.cota/`：可选 Web 应用数据库与签名密钥，不随 Bot 定义分享。

模板不包含凭证、安装环境或历史记录。完整对话通过 Cota Store 查询；执行事件、运行元数据和 DST 快照也保存在 Store，不是 Pi 的独立会话文件。历史恢复需要继续使用同一个 session_id；新建会话不会自动合并旧对话。`cota shell` 每次启动会创建新会话；跨重启接续可通过使用固定 session_id 的 API 客户端实现。

## 测试

在仓库根目录执行：

```bash
python -m pytest tests/test_bot_templates.py tests/integration/test_example_bots.py -q
```

集成测试直接加载 weather 模板，以及 tests/fixtures/bots 下仅供测试的对话和业务规则配置，运行真实 Pi 子进程、OpenAI 客户端、Cota 工具和 SQLite。仅对模型 HTTP 提供固定响应，并通过显式注册的测试工具提供天气数据；Node HTTP 工具由独立测试验证，不消耗 API Key，也不依赖公网。
这验证程序链路，不代表已经验证真实模型的推理质量或公共天气服务的可用性。实际体验请配置自己的模型后按 weather README 的场景测试。

配置好 weather 模型后，可在其目录执行 `cota eval`，或从仓库执行 `cota eval --config cota_projects/weather`。默认显示进度，输出报告、结构化结果和逐轮证据；加 `--debug` 额外保存 Bot 模型请求。评委优先 evaluator，未配置时 default。详见[评测指南](../docs/src/development/evaluation.md)。

## 旧示例迁移

当前仅保留 weather 作为入门、业务规则、Skill、工具调用及评测示例。其它历史示例不再随包分发；`cota init` 不会删除或修改用户以前生成的项目。基础聊天、会话隔离和业务取消的回归覆盖保留在测试专用配置中。

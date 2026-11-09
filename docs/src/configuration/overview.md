# 配置总览

一个 Bot 文件夹同时保存可分享的业务定义和本次部署需要的资源设置。先建立最小配置，再按业务增加 Skill、工具和 Policy。

```text
my_bot/
├── agent.yml          # Bot 身份、对话、工具范围、Policy 策略
├── endpoints.yml      # 模型、存储、平台连接
├── skills/            # 可选：Skill 说明和引用资源
│   └── order/SKILL.md
├── policy/            # 可选：业务案例标注
│   └── data.yml
└── workspace/         # 运行时工作目录
```

| 配置 | 负责什么 | 使用位置 |
| --- | --- | --- |
| `agent.yml` | deploy、system、dialogue、environment、tools、policy、knowledge | `Agent.load_from_path()` 校验并加载 |
| `endpoints.yml` | base_store、llms、embeddings、channels | Store / LLM / Policy 资源及部署入口 |
| `skills/**/SKILL.md` | 业务能力说明与资源目录 | Pi 发现，模型按需通过 `read` 阅读 |
| `policy/*.yml` | `policies` / `name` / `steps` 业务案例 | Policy 提供当前请求的 guidance |
| `models/policy.json` | 需要训练的 Policy 产物 | 训练后加载，源或配置变化会校验失效 |

`Agent.load_from_path()` 只加载 Bot 资源，不启动监听服务、Channel 或定时 SchedulerService。CLI 部署入口另外合并两份 YAML 中的 `channels`；`endpoints.yml` 覆盖同名 channel 的字段。SDK 创建服务时显式传递 `channel_config`。

模型的 `key`、`apibase`、`model` 直接写实际字符串，不进行环境变量替换。分享 Bot 文件夹时用可填写的配置模板交付，部署凭证由接收者配置。

Bot 顶层字段采用明确校验，未知字段会报错。旧 DPL、Action、task.yml 编排、Skill 自动执行脚本和旧 Web transport 配置不能沿用。先按 [快速开始](../tutorial/quick_start.md) 跑通一个示例，再阅读需要的配置项。

实现入口：`cota/config.py`、`cota/agent.py`、`cota/__main__.py`。

相关文档：[Agent 配置](agent.md) · [Endpoints 配置](endpoints.md) · [Policy 配置](policy.md) · [Skills](../skills/overview.md) · [分享 Bot](../deployment/sharing.md)

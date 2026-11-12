# Skills 概述

Skill 以稳定名称标识业务能力，正文是模型按需读取的操作文档。Cota 使用 Pi coding-agent 1.4.0 的公开组件发现、解析和展示 Skill，并通过 Pi 的 `read(path)` 工具读取文档。实际业务能力由 Pi 原生工具、内置 Node HTTP 工具、Python 扩展或显式接入的工具进程提供。

一个任务可以读取多个 Skill，也可以重复读取同一个 Skill。读取文档不会创建独立执行器、切换模型或改变工具权限。

## 目录与文档

Bot 的 Skill 放在该 Bot 的 `skills/` 下：

```text
bot/
├── agent.yml
├── endpoints.yml
└── skills/
    └── weather/
        ├── SKILL.md
        ├── references/
        │   └── response-format.md
        └── images/
            └── example.png
```

`SKILL.md` 使用 Pi 支持的 YAML frontmatter 和 Markdown 正文：

```markdown
---
name: weather
description: 查询指定城市的天气，并解释查询结果。
---

# 天气查询

1. 如果用户没有给出城市，直接询问用户确认。
2. 使用 Bot 已允许的 web_fetch 查询天气服务。
3. 根据工具结果回复；失败时说明原因，不编造天气。
4. 需要解析细节时，读取同目录 references/response-format.md。
```

`description` 帮助模型选择文档，正文提供操作步骤。名称、格式诊断和重复名称的处理遵循 Pi loader。文档中的工具名称、脚本或依赖说明不会自动注册工具或安装环境。

## 发现与读取

`Agent.load_from_path` 只将当前 Bot 的 `skills/` 作为显式资源路径交给 worker。每次 worker 启动时：

1. 用 `loadSkillsFromDir` 发现候选 Skill。
2. 检查真实文件路径与目录边界，排除越界符号链接。
3. 用 `loadSkills(..., includeDefaults: false)` 完成加载和去重。
4. 用 `formatSkillsForPrompt` 将名称、描述和位置组成目录提示。

不会自动加载用户主目录、全局或其他项目的 Skill。系统提示包含目录；正文在模型调用 `read` 后作为工具结果进入上下文，不会依据 `active_skill` 自动注入。

模型调用示例：

```json
{"path": "/opt/my-bot/skills/weather/SKILL.md"}
```

`read` 复用 Pi 的 `createReadToolDefinition`，支持文本的 `offset` / `limit` 分页和支持格式的图片。在默认 none 环境中，Cota 对文件访问、内容读取和图片检测检查资源边界，只能读取已发现 Skill 的目录内的普通文件。

显式启用 personal 的 machine 环境后，同一个 read 也可以读取宿主机业务文件；与其他可用原生工具共享配置的起始工作目录。machine 不构成沙箱。没有 Skill 时，none 不提供 read，machine 按依赖可用性提供原生工具。八个原生工具名称始终保留给 Pi，不能注册同名业务扩展。详见 [工具与执行环境](../concepts/tool-adapters.md)。

## 记录与恢复

成功读取已发现的 `SKILL.md` 后，Python 在 `tool_result.payload.resource` 中标记 `kind="skill"` 和 Skill 名称，并将 `DST.active_skill` 更新为该文档的 Skill 名称。它只表示最近成功读取的 Skill：

- 读取引用文件、图片或读取失败不会改变标签。
- 读取另一份 Skill 文档会更新标签，但之前的文档仍在工具历史中。
- 回复结束或等待用户时保留标签；它不参与提示词、工具权限或 Policy 路由。
- 工具事件不自动携带此标签；Trace 保留实际调用及顺序，不自动将后续工具归属到最后读取的 Skill。

每次资源读取都记录 `ToolResultEvent(tool="read")`。Node 发送 `tool_result`，Python 保存相关事件后才返回确认；保存失败会停止继续执行。工具结果保存在 DST events；context_messages 由这些事实推导，并随快照缓存。

缺少信息时，模型直接回复问题，本轮正常完成。用户回答后，同一会话的新 run 从已保存的对话继续；问题和最终答案都保存为 `bot_utter`，再经 Channel 投递。Skill 阅读只留下执行证据，不产生激活或暂停状态。

## 工具与依赖

Bot 的 `agent.yml` 中 `tools.allow` / `tools.deny` 控制业务工具，deny 优先于 allow。Skill 文档不授予权限；不存在按 Skill 设置的权限交集或 `skill_only` 门槛。Pi 原生工具由 `environment` 控制。

需要自定义能力时，在 Bot 启动服务前注册 `Tool` / `FunctionTool`，或接入 MCP。需要独立依赖时显式连接 `SubprocessToolClient`。Skill 目录中存在 `.venv` 或脚本不会自动启动它们；独立进程也不等于安全 sandbox。

业务改进通过查看 Trace、围绕 Skill 名称编写或改写对话式 Policy 文件实现，见 [Skill、Trace 与 Policy](../concepts/skill-policy.md)。Policy 每次 prepare 都可指导模型选择、组合和执行；不会自动晋升标注或修改 Skill 文件。

## 验证与排查

- 目录缺失或文档未出现：检查 Bot 资源路径、frontmatter 和 Debug 页面中对应运行的 Skills 诊断。
- `read` 失败：检查实际文件是否在已发现 Skill 的目录内，以及路径或符号链接是否越界。
- 文档可读但业务工具不可用：检查工具是否注册、Bot 权限和后端配置；修改文档不会改变工具权限。
- 核对恢复行为：用同一 session_id 查询 Store，检查 `context_messages` 和 `tool_result.payload.resource`。

仓库中的 `bots/weather/skills/weather/SKILL.md` 展示最小 Skill。运行机制见 [Pi Runtime](../concepts/pi-runtime.md)，能力接入见 [工具接入](../concepts/tool-adapters.md)，状态、稳定事件结构与恢复接口见 [DST](../concepts/dst.md)。

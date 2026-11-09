# Cota 使用手册

Cota 是 **Bot 开发与部署平台**，帮助开发者定义业务能力、注入业务规则、接入工具，并把完整 Bot 交付给自己或别人使用。它面向个人助手、客服、群聊助手等场景；这些场景共享一套 Bot 定义、执行与持久化架构。

本手册描述当前开发代码。已发布包是否包含这些能力，应以对应版本为准。先阅读 [安装](installation/install.md)，不要直接套用旧版安装包的配置或接口。

## 开始使用

| 你要做什么 | 从这里开始 |
| --- | --- |
| 在 shell 验证一个 Bot | [快速开始](tutorial/quick_start.md) |
| 编写角色、Skill 和业务规则 | [Agent 配置](configuration/agent.md)、[Skill](skills/overview.md)、[对话式 Policy 标注](concepts/skill-policy.md) |
| 让 Policy 随当前对话提供合适的指导 | [Policy 训练与推理](concepts/trainable-policy.md) |
| 查看 prompt、工具调用与持久状态 | [Debug 与执行记录](deployment/debug.md) |
| 给别人分享聊天链接或 Bot 文件夹 | [交付与分享](deployment/sharing.md) |
| 对接网页、小程序或自己的账号体系 | [应用契约](deployment/application.md)、[Web 接入](deployment/api.md) |
| 接入飞书或群聊 | [飞书](deployment/feishu.md)、[群聊](deployment/group.md) |
| 修改框架或新增测试 | [模块地图](concepts/modules.md)、[开发与验证](development/testing.md) |

## 六个核心概念

1. **Bot**：交付单位，由配置、业务说明、Policy、工具能力和部署资源共同组成。
2. **Skill**：以 `SKILL.md` 描述业务能力和 SOP，模型按需读取与组合。
3. **Tool**：实际执行的代码、API、MCP 或工具进程；权限独立于 Skill 文本。
4. **Event / Trace**：事件保存执行事实，Trace 按运行呈现证据；读过 Skill 不代表业务已完成。
5. **DST / Store**：DST 应用事件并投影状态；Store 保存事件、快照和必要的辅助记录。
6. **Policy**：运营编写的对话式业务案例，以及选择这些案例形成指导的可扩展策略。

Pi Agent Core 驱动模型—工具循环，Cota 负责业务指导、能力边界、状态、交付与追踪。
Pi 的 Skill 资源组件与 Agent Core 是不同层；Cota 当前不使用 AgentSession 管理会话。

完整职责见 [定位与架构](concepts/raas_architecture.md)，尚未实现的 RSI 和交付能力见 [能力边界与规划](concepts/roadmap.md)。

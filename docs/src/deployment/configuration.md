# 部署配置入口

Bot 行为与部署资源分开配置，避免同一字段散落在不同文件中。支持字段的详细列表以配置参考为准。

| 内容 | 配置位置 | 参考 |
| --- | --- | --- |
| Bot 角色、Pi 参数、direct/group、passive/proactive | agent.yml 的 system/dialogue | [Agent](../configuration/agent.md) |
| 工具允许/拒绝范围 | agent.yml 的 tools | [工具接入](../concepts/tool-adapters.md) |
| 自用或对外服务、原生工具执行环境 | agent.yml 的 deploy / environment | [Agent 配置](../configuration/agent.md) |
| Policy 方法、预算和训练产物 | agent.yml 的 policy | [Policy](../configuration/policy.md) |
| 运营编写的业务对话案例 | policy/*.yml | [标注格式](../concepts/skill-policy.md) |
| 模型、embedding、Store 与用户记忆 | endpoints.yml | [Endpoints](../configuration/endpoints.md) |
| Channel 默认值 | agent.yml 的 channels | [Channel](../concepts/channel.md) |
| Channel 部署值与凭据 | endpoints.yml 的 channels，同名字段覆盖前者 | [Web](api.md)、[飞书](feishu.md)、[自定义 Channel](../development/channel-plugins.md) |
| HTTP host/port/TLS、是否挂载聊天页面 | cota run 参数 | [CLI](cli.md) |
| 登录、会话归属和成员权限 | 外围应用的适配器，或可选 Web app | [应用契约](application.md) |

只在一个地方定义事实：数据库地址不放在 Skill 里，模型 key 不放在 Policy 里，监听端口不配置为 channels.web.port。
配置读取不会自动展开环境变量；模型凭据直接填写 endpoints.yml。

## 常见部署组合

- 本地：direct Bot + SQLite + shell。
- 独立聊天链接：direct/group Bot + 持久 Store + `--chat-app`。
- 已有业务应用：Web Channel + ExternalAccess，外围保留自己的账号、会话列表和成员系统。
- 飞书：配置 feishu，关闭不需要的 Web；同一 Bot 部署固定 direct 或 group。
- 公司 IM / 自定义平台：安装 Channel 包，在 endpoints.yml 启用对应类型，再用 `cota run` 启动；Webhook 共用服务端口，平台验签和授权由适配器负责。

没有外部身份适配器的核心 GuestAccess 只支持单用户私有会话；群聊需外部成员授权或配套聊天应用。
部署流程见 [部署指南](guide.md)，不要使用旧版 /tracker、workspace 文件操作接口或 JWT 全局开关配置。

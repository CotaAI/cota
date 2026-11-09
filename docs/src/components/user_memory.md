# UserMemory：跨会话用户记忆

UserMemory 按 `user_id` 保存偏好、个人资料和业务备注。同一用户的多个会话共享这些数据；会话历史、工具执行记录和运行状态由 DST / Store 保存。

## 后端选择

Agent 根据 `endpoints.yml` 的 `base_store` 创建记忆后端：内存配置使用 `MemoryUserMemory`，`type: sql` 使用 `SQLUserMemory`。SQL 初始化失败会向上报错，不会静默退回内存。

建议显式配置 SQL dialect 和数据库路径，让 Store 与记忆使用同一数据库参数：

```yaml
base_store:
  type: sql
  dialect: sqlite
  db: .cota/state.db
```

通过 `Agent.load_from_path()` 加载时，SQLite 相对路径以 Bot 目录解析。内存后端只在当前进程存活期间保留数据。

## 可信应用接口

用户记忆由应用维护，默认不向模型注册读写工具。群聊不把某个成员的私有偏好当成整个群的上下文。

受信任应用可调用 `get/set/delete/get_all/search`；异步应用使用 `aget/aset/adelete/aget_all/asearch`，避免同步数据库操作阻塞事件循环。例如：

```python
await agent.user_memory.aset("alice", "language", "zh-CN")
preferences = await agent.user_memory.aget_all("alice")
```

## 与 prompt 的关系

每条新输入前 Processor 刷新用户记忆，DST 用 `user_context_updated` 同时记录身份和当时的记忆。prompt 的 `{{user_context_text}}` 使用这一已记录状态；历史恢复不会重新读取实时记忆。应用更新记忆后，下一条输入会再次刷新完整上下文。

`mcp_endpoint`、`mcp_auth_token` 是连接配置保留键。只有可信应用通过底层 UserMemory 接口登记；不向模型暴露。它们在进入 DST 用户上下文时被过滤，不会作为偏好写进 prompt。

持有 `agent.user_memory` 的应用代码本身具有可信权限。部署方仍需负责真实用户认证、数据库访问控制和敏感数据管理；不能让外部请求直接选任意 user_id 调用这些接口。

实现入口：`cota/executor/user_memory.py`、`cota/dst.py`、`cota/processor.py`。

相关文档：[DST](../concepts/dst.md) · [MCP](mcp.md) · [Endpoints 配置](../configuration/endpoints.md) · [群聊](../deployment/group.md)

# MCP：后端连接设施

Cota 保留 MCP 客户端供可信应用连接、发现和调用外部服务。默认 Agent 不向模型注册 MCP 工具；应用负责授权和客户端生命周期。

## 两种连接方式

| 客户端 | 传输与用途 |
| --- | --- |
| `MCPClientWrapper` | stdio，按部署方提供的启动参数创建并连接本地 MCP 子进程 |
| `RemoteMCPClient` | HTTP/SSE，连接当前用户登记的远程设备服务 |

`MCPClientWrapper.ensure_connected()` 使用 SDK 的 `stdio_client(server_params)` 启动子进程，并管理该传输的生命周期；它不连接一个事先独立启动的 stdio 进程。

远程 SSE 是当前 MCP 适配器的实现，不是 Web 聊天 Channel 的传输方式。Cota 自定义 `SubprocessToolClient` 则使用另一套 JSON-lines 协议，不能直接把它当 MCP 客户端。

## 用户设备工具

应用可使用 MCPConnectionPool 管理用户设备连接，调用方须绑定经过认证的用户身份。连接池不会自动把远端能力暴露给模型。

连接信息必须由已认证的可信应用代码登记：

```python
await agent.user_memory.aset("alice", "mcp_endpoint", "https://device.example.com/sse")
await agent.user_memory.aset("alice", "mcp_auth_token", "replace-with-device-token")
```

地址应填写服务实际提供的 SSE endpoint。`mcp_endpoint` 和 `mcp_auth_token` 是保留键：不进入 DST 的用户记忆 prompt。不要指导用户通过自然语言让模型写入连接凭证。

连接池按应用提供的 `user_id` 读取连接配置。私有设备地址允许由可信应用登记，因此设备登记本身需要应用完成认证和授权；远端服务仍需执行自己的权限控制。

## 连接池与关闭

MCPConnectionPool 以用户为键复用连接，同一用户的不同会话可共享客户端。endpoint 或 token 变化时替换旧连接。默认容量为 100，超出时回收最久未用连接；`cleanup_idle()` 可按默认 300 秒闲置阈值清理，但调用方需要安排清理时机。

stdio 和远程客户端都使用 `MCPSessionOwner`。transport 与 session 上下文始终由同一 owner task 进入和退出，避免 AnyIO cancel scope 跨任务关闭。并发连接等待者共享初始化；取消一个等待者不应关闭仍由其他等待者或调用方使用的连接，最后一个尚未交付的等待者取消时回收资源。旧连接关闭也不能覆盖新一代连接状态。

独立使用客户端时在 `finally` 中 `await client.close()`，持有连接池时 `await pool.close_all()`。应用负责安排池的清理和关闭。

实现入口：`cota/executor/mcp.py`、`cota/executor/mcp_remote.py`、`cota/executor/mcp_lifecycle.py`、`cota/executor/mcp_pool.py`。

相关文档：[Tool 适配](../concepts/tool-adapters.md) · [用户记忆](user_memory.md) · [Agent](../concepts/agent.md) · [能力边界](../concepts/roadmap.md)

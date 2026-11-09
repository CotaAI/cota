# 2026-11-05 全仓代码审计与测试补全

本次以开始工作时的 feature/2.0 工作树为基线，保留此前已有的未提交修改。
不是按 Git HEAD 的差异统计本次改动；该分支本身已经包含大量 2.0 重构。

## 范围和方法

- 起始清单：216 个第一方可执行源码文件（203 Python、7 mjs、5 js、1 shell）。
- 最终清单：227 个（215 Python、7 mjs、4 js、1 shell），逐项列在下表。
- 排除虚拟环境、下载的 Node/Pi/vendor、node_modules、运行 workspace、构建产物和 Git 元数据。
- 所有文件执行语法检查；Python 全仓执行 Ruff F/E9。生产实现按职责分组阅读，结合调用引用、动态注册、事件重放和边界测试审查。
- 测试文件按静态诊断、覆盖缺口和行为合同审查，并执行全套。没有将“搜索不到直接调用”当作删除动态入口的充分理由。
- HTML/CSS 页面随应用模块审阅；JavaScript 另有 Node 测试，不计入 Python 覆盖率。

## 修复与清理

| 领域 | 核心改动 | 回归证据 |
| --- | --- | --- |
| Pi/Trace | 在副作用前保存经 Pi 校验/转换的实参，必要时另存模型提议；batch follower 保持来源。JSON 数字往返允许 1.0/1，但不混同 true/1 | test_trace_runtime.py |
| Store | MySQL/PostgreSQL 读取 metadata/snapshot/events 使用同一 repeatable-read 视图；SQLite 保留显式读事务 | test_read_isolation.py；原持久化合同 |
| LLM/Knowledge | 补齐 temperature 透传、tool-only 响应、明确关闭客户端；移除析构建连接和重复 OpenAI/RAG 请求实现 | llm/test_client_contract.py；test_knowledge.py |
| Web/Cmdline | 有界回放缓冲隔离慢 peer、完整握手/清理生命周期、错误脱敏、可取消 stdin；Web app 使用 Bot 自己的配置目录 | test_channel_audit.py；原 HTTP/WS 集成 |
| MCP | 单任务持有 SDK transport/session 上下文；共享初始化取消隔离、早期 close 和交接清理；token 更新重连和 TextContent 提取 | executor/test_mcp_lifecycle.py、test_mcp_concurrency.py、test_audit_security.py |
| Scheduler | 用户过滤；触发互斥；配置先验证，提交成功再替换缓存/执行 callback；运行中更新不被旧 callback 覆盖；预检查超时清理进程树 | scheduler/test_service_regressions.py、test_atomic_updates.py、test_precheck_process_tree.py |
| Tool server | 按能力白名单导出，保留 JSON 返回类型；EOF/异常/取消/shutdown 都清理一次 | executor/test_audit_security.py、test_tool_server_cleanup.py |
| HTTP/Memory | 连接时检查实际 DNS 地址，禁用自动跳转；可信 MCP 连接配置不能经 memory 工具或自动上下文进入事件/prompt | executor/test_audit_security.py；test_memory_context_boundary.py |
| CLI/模板 | shell 退出关闭 Agent；定时输入走同一队列；拒绝不完整 TLS；持续排空隧道 stdout 并回收子进程；init/发布不复制 .cota 状态 | test_cli_lifecycle.py、test_cli_scheduler.py、test_bot_templates.py |
| Policy | 可容纳完整案例时，不因额外诊断前缀导致案例被错误丢弃 | test_skill_policy.py |
| 测试基础 | 独立临时 workspace；移除自定义过期 event_loop fixture；未等待协程和 unraisable 异常按失败处理 | tests/conftest.py、pyproject.toml |

确认无调用的旧 HTTP wrapper、slot/parser、旧界面生成器/Service Worker/图标、action/utter 转换器已删除。
旧 `tests/test_llm.py` 未 await 被测异步调用，会产生假通过，已由实际 adapter 合同测试替代。
清理未使用导入、重复分支和无效私有参数；保留动态工具注册、MCP/飞书进程入口、Pi 分发代码及仍有明确职责的公共 API。
移除未使用的 sanic-cors、sanic-jwt、questionary、gunicorn、setuptools 和 Pillow 运行依赖；更新 uv.lock。
旧 front.md 自动生成界面的入口文档改为实际可选聊天应用说明，历史架构页明确标注不适用。

## 验证结果

最终冻结代码运行 `python scripts/check.py --coverage` 成功退出（exit 0）。

| 检查 | 审计前 | 最终结果 |
| --- | --- | --- |
| 第一方源码语法 | 216 文件通过 | 227 文件通过 |
| Ruff F/E9 | 99 个诊断 | 0 个诊断 |
| Python 测试 | 993 passed，1 skipped | **1155 passed，1 skipped** |
| Node 测试 | 未作为基线统计 | **42 passed，0 skipped**，4 个套件 |
| Python 语句+分支综合覆盖 | 76.29% | **85.74%** |
| Python 语句覆盖 | 78.56% | **88.24%** |
| Python 分支覆盖 | 69.23% | **78.07%** |

新增 17 个测试模块，并补充现有用例；测试总数净增 162。
最终 Python 全套耗时 203.82 秒。唯一跳过项为 MemoryStore 不适用的 SQL projection 测试；
20 个警告来自现有 websockets 兼容依赖的弃用提示，无未等待协程或 unraisable 异常。
`uv lock --check --offline`、刷新 editable 元数据后的 `uv pip check`、`git diff --check` 均通过。

首轮回归发现并修正了天气 HTTP mock 的 connector 生命周期、依赖过去时间的旧 scheduler 用例，
以及覆盖率模式下子进程启动速度影响超时测试的问题；最终结果不是忽略失败或只跑新增用例得到的。

统一检查：`python scripts/check.py --coverage`。详见 [测试指南](../../tests/README.md)。
本地生成 coverage.json / coverage.xml，不纳入 Git；CI 上传同样产物。

## 验证边界

- 模型调用通过可控回包验证框架合同，没有评价真实模型回答质量。
- 测试运行真实本地 Pi、SQLite、MCP SDK 和 localhost HTTP/WS；公网飞书、天气、隧道未调用。
- MySQL/PostgreSQL 读隔离有接口顺序合同测试，未连接实际数据库；仍需部署环境验证。
- 非 POSIX 控制台 fallback 和四个平台 wheel 构建需各目标环境验证；本次未实际执行新增 GitHub Actions。
- scheduler/async_task 仍仅用于本地 shell；服务模式的 Pi 调用入口拒绝这些工具。未来开放多人定时投递时，必须单独完成可信会话归属和投递路由，不能直接复用模型提供的 session_id。
- 覆盖率数字不能证明没有缺陷；动态入口不能因覆盖率低而删掉。

## 逐文件清单

“新增”相对于本次审计开始时的源码清单。保留既有工作树改动不意味着该文件与 Git HEAD 相同。

| 文件 | 领域 | 处理与检查 |
| --- | --- | --- |
| [cota/__init__.py](../../cota/__init__.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/__main__.py](../../cota/__main__.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/agent.py](../../cota/agent.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/annotation_cli.py](../../cota/annotation_cli.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/annotation_files.py](../../cota/annotation_files.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/application.py](../../cota/application.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/__init__.py](../../cota/channels/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/base.py](../../cota/channels/base.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/cmdline.py](../../cota/channels/cmdline.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/delivery.py](../../cota/channels/delivery.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/events.py](../../cota/channels/events.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/manager.py](../../cota/channels/manager.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/platforms/__init__.py](../../cota/channels/platforms/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/platforms/feishu.py](../../cota/channels/platforms/feishu.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/platforms/feishu_worker.py](../../cota/channels/platforms/feishu_worker.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/queue.py](../../cota/channels/queue.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/runner.py](../../cota/channels/runner.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/utils/__init__.py](../../cota/channels/utils/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/utils/cota.js](../../cota/channels/utils/cota.js) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/web/__init__.py](../../cota/channels/web/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/web/access.py](../../cota/channels/web/access.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/web/base.py](../../cota/channels/web/base.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/web/service.py](../../cota/channels/web/service.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/channels/web/transport.py](../../cota/channels/web/transport.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/config.py](../../cota/config.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/constant.py](../../cota/constant.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/conversation.py](../../cota/conversation.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/debug/__init__.py](../../cota/debug/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/debug/inspector.py](../../cota/debug/inspector.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/debug/server.py](../../cota/debug/server.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/debug/static/app.js](../../cota/debug/static/app.js) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/delivery_store.py](../../cota/delivery_store.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/dst.py](../../cota/dst.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/__init__.py](../../cota/events/__init__.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/assistant.py](../../cota/events/assistant.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/context.py](../../cota/events/context.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/event.py](../../cota/events/event.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/history.py](../../cota/events/history.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/resources.py](../../cota/events/resources.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/events/tool.py](../../cota/events/tool.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/execution_logging.py](../../cota/execution_logging.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/__init__.py](../../cota/executor/__init__.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/mcp.py](../../cota/executor/mcp.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/mcp_lifecycle.py](../../cota/executor/mcp_lifecycle.py) | 工具、MCP、Scheduler | 新增；实现审阅；语法/静态；相关回归 |
| [cota/executor/mcp_pool.py](../../cota/executor/mcp_pool.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/mcp_remote.py](../../cota/executor/mcp_remote.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/scheduler/__init__.py](../../cota/executor/scheduler/__init__.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/scheduler/service.py](../../cota/executor/scheduler/service.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/scheduler/store.py](../../cota/executor/scheduler/store.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/scheduler/types.py](../../cota/executor/scheduler/types.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tool_process.py](../../cota/executor/tool_process.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tool_servers/__init__.py](../../cota/executor/tool_servers/__init__.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tool_servers/default_tool_server.py](../../cota/executor/tool_servers/default_tool_server.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tool_servers/tool_server_base.py](../../cota/executor/tool_servers/tool_server_base.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/__init__.py](../../cota/executor/tools/__init__.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/ask_user.py](../../cota/executor/tools/ask_user.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/async_task.py](../../cota/executor/tools/async_task.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/base.py](../../cota/executor/tools/base.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/http_request.py](../../cota/executor/tools/http_request.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/mcp_client.py](../../cota/executor/tools/mcp_client.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/notify.py](../../cota/executor/tools/notify.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/proxy.py](../../cota/executor/tools/proxy.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/registry.py](../../cota/executor/tools/registry.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/reply_user.py](../../cota/executor/tools/reply_user.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/scheduler.py](../../cota/executor/tools/scheduler.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/tools/user_memory.py](../../cota/executor/tools/user_memory.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/executor/user_memory.py](../../cota/executor/user_memory.py) | 工具、MCP、Scheduler | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/group.py](../../cota/group.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/inputs.py](../../cota/inputs.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/knowledge/__init__.py](../../cota/knowledge/__init__.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/knowledge/knowledge.py](../../cota/knowledge/knowledge.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/knowledge/llm_knowledge.py](../../cota/knowledge/llm_knowledge.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/__init__.py](../../cota/llm/__init__.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/base.py](../../cota/llm/base.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/custom.py](../../cota/llm/custom.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/factory.py](../../cota/llm/factory.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/llm.py](../../cota/llm/llm.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/observation.py](../../cota/llm/observation.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/llm/openai.py](../../cota/llm/openai.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/message/message.py](../../cota/message/message.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/participation.py](../../cota/participation.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/__init__.py](../../cota/policy/__init__.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/base.py](../../cota/policy/base.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/catalog.py](../../cota/policy/catalog.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/context.py](../../cota/policy/context.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/factory.py](../../cota/policy/factory.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/model.py](../../cota/policy/model.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/resources.py](../../cota/policy/resources.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/retrieval.py](../../cota/policy/retrieval.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/policy/training.py](../../cota/policy/training.py) | Policy 与标注 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/processor.py](../../cota/processor.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/run_metadata.py](../../cota/run_metadata.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/__init__.py](../../cota/runtime/__init__.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi/engine.mjs](../../cota/runtime/pi/engine.mjs) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi/skills.mjs](../../cota/runtime/pi/skills.mjs) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi/worker.mjs](../../cota/runtime/pi/worker.mjs) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi/worker.test.mjs](../../cota/runtime/pi/worker.test.mjs) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_bridge.py](../../cota/runtime/pi_bridge.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_context.py](../../cota/runtime/pi_context.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_distribution.py](../../cota/runtime/pi_distribution.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_runtime.py](../../cota/runtime/pi_runtime.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_setup.py](../../cota/runtime/pi_setup.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/runtime/pi_trace.py](../../cota/runtime/pi_trace.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/server.py](../../cota/server.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/snapshots.py](../../cota/snapshots.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/store.py](../../cota/store.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/templates.py](../../cota/templates.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/trace.py](../../cota/trace.py) | 状态、事件与 Pi 执行 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/utils/__init__.py](../../cota/utils/__init__.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/utils/common.py](../../cota/utils/common.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/utils/io.py](../../cota/utils/io.py) | 模型、知识、配置与工具函数 | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/webapp/__init__.py](../../cota/webapp/__init__.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/webapp/access.py](../../cota/webapp/access.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/webapp/app.py](../../cota/webapp/app.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/webapp/registry.py](../../cota/webapp/registry.py) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [cota/webapp/static/app.js](../../cota/webapp/static/app.js) | 应用、Channel、Debug | 保留/必要修正；实现审阅；语法/静态；相关回归 |
| [docs/theme/custom.js](../../docs/theme/custom.js) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [hatch_build.py](../../hatch_build.py) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [restart.sh](../../restart.sh) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [scripts/application_example.py](../../scripts/application_example.py) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [scripts/bundle_runtime.py](../../scripts/bundle_runtime.py) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [scripts/check.py](../../scripts/check.py) | 打包、示例与开发脚本 | 新增；实现审阅；语法/静态；不代表发布环境实测 |
| [scripts/smoke_installed.py](../../scripts/smoke_installed.py) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [setup.py](../../setup.py) | 打包、示例与开发脚本 | 保留/必要修正；实现审阅；语法/静态；不代表发布环境实测 |
| [tests/__init__.py](../../tests/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/__init__.py](../../tests/channels/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/test_feishu.py](../../tests/channels/test_feishu.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/test_feishu_relay.py](../../tests/channels/test_feishu_relay.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/channels/test_group_adapters.py](../../tests/channels/test_group_adapters.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/test_input_ids.py](../../tests/channels/test_input_ids.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/test_manager.py](../../tests/channels/test_manager.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/channels/test_web.py](../../tests/channels/test_web.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/conftest.py](../../tests/conftest.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/debug/viewer.test.mjs](../../tests/debug/viewer.test.mjs) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/__init__.py](../../tests/executor/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/test_async_task_identity.py](../../tests/executor/test_async_task_identity.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/executor/test_audit_security.py](../../tests/executor/test_audit_security.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/executor/test_mcp_concurrency.py](../../tests/executor/test_mcp_concurrency.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/executor/test_mcp_lifecycle.py](../../tests/executor/test_mcp_lifecycle.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/executor/test_service_mode_security.py](../../tests/executor/test_service_mode_security.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/test_tool_process.py](../../tests/executor/test_tool_process.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/test_tool_registry.py](../../tests/executor/test_tool_registry.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/test_tool_server_cleanup.py](../../tests/executor/test_tool_server_cleanup.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/executor/test_tools_base.py](../../tests/executor/test_tools_base.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/executor/test_user_memory.py](../../tests/executor/test_user_memory.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/__init__.py](../../tests/integration/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_advanced_scenarios.py](../../tests/integration/test_advanced_scenarios.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_advanced_scenarios_2.py](../../tests/integration/test_advanced_scenarios_2.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_bot_scenarios.py](../../tests/integration/test_bot_scenarios.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_delivery_application.py](../../tests/integration/test_delivery_application.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_example_bots.py](../../tests/integration/test_example_bots.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/integration/test_feishu_application.py](../../tests/integration/test_feishu_application.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/llm/__init__.py](../../tests/llm/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/llm/test_client_contract.py](../../tests/llm/test_client_contract.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/llm/test_llm.py](../../tests/llm/test_llm.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/resource_fixtures.py](../../tests/resource_fixtures.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/scheduler/__init__.py](../../tests/scheduler/__init__.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/scheduler/test_atomic_updates.py](../../tests/scheduler/test_atomic_updates.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/scheduler/test_precheck_process_tree.py](../../tests/scheduler/test_precheck_process_tree.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/scheduler/test_service_regressions.py](../../tests/scheduler/test_service_regressions.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/scheduler/test_store.py](../../tests/scheduler/test_store.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/scheduler/test_types.py](../../tests/scheduler/test_types.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_annotation_cli.py](../../tests/test_annotation_cli.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_annotation_worksheet.py](../../tests/test_annotation_worksheet.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_application.py](../../tests/test_application.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_application_server.py](../../tests/test_application_server.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_assistant_carriers.py](../../tests/test_assistant_carriers.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_bot_templates.py](../../tests/test_bot_templates.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_channel_audit.py](../../tests/test_channel_audit.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_channel_scheduling.py](../../tests/test_channel_scheduling.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_chat_app.py](../../tests/test_chat_app.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_chat_registry.py](../../tests/test_chat_registry.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_check_inventory.py](../../tests/test_check_inventory.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_cli_lifecycle.py](../../tests/test_cli_lifecycle.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_cli_scheduler.py](../../tests/test_cli_scheduler.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_debug_shell.py](../../tests/test_debug_shell.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_debug_viewer.py](../../tests/test_debug_viewer.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_delivery_dispatcher.py](../../tests/test_delivery_dispatcher.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_delivery_store.py](../../tests/test_delivery_store.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_dst.py](../../tests/test_dst.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_dst_invariants.py](../../tests/test_dst_invariants.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_endpoint.py](../../tests/test_endpoint.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_event_sourcing.py](../../tests/test_event_sourcing.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_execution_logging.py](../../tests/test_execution_logging.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_group_bus.py](../../tests/test_group_bus.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_group_conversation.py](../../tests/test_group_conversation.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_group_store.py](../../tests/test_group_store.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_incremental_context.py](../../tests/test_incremental_context.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_input_identity.py](../../tests/test_input_identity.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_knowledge.py](../../tests/test_knowledge.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_memory_context_boundary.py](../../tests/test_memory_context_boundary.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_message.py](../../tests/test_message.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_participation_judge.py](../../tests/test_participation_judge.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_participation_scheduling.py](../../tests/test_participation_scheduling.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_persistence_contract.py](../../tests/test_persistence_contract.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_behaviors.py](../../tests/test_pi_behaviors.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_cleanup.py](../../tests/test_pi_cleanup.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_config.py](../../tests/test_pi_config.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_distribution.py](../../tests/test_pi_distribution.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_processor.py](../../tests/test_pi_processor.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_runtime.py](../../tests/test_pi_runtime.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_skill_discovery.py](../../tests/test_pi_skill_discovery.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_pi_skills.py](../../tests/test_pi_skills.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_proactive_quality.py](../../tests/test_proactive_quality.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_processor.py](../../tests/test_processor.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_read_isolation.py](../../tests/test_read_isolation.py) | 测试与夹具 | 新增；语法/静态检查；全套回归执行 |
| [tests/test_read_resources.py](../../tests/test_read_resources.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_run_metadata.py](../../tests/test_run_metadata.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_run_recovery.py](../../tests/test_run_recovery.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_runtime_persistence.py](../../tests/test_runtime_persistence.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_server.py](../../tests/test_server.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_server_contract.py](../../tests/test_server_contract.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_skill_policy.py](../../tests/test_skill_policy.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_skill_policy_runtime.py](../../tests/test_skill_policy_runtime.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_store.py](../../tests/test_store.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_tool_event_contract.py](../../tests/test_tool_event_contract.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_trace.py](../../tests/test_trace.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_trace_runtime.py](../../tests/test_trace_runtime.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_trainable_policy.py](../../tests/test_trainable_policy.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_user_context_event.py](../../tests/test_user_context_event.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_web_access.py](../../tests/test_web_access.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_web_app_integration.py](../../tests/test_web_app_integration.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_web_execution.py](../../tests/test_web_execution.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_web_revocation.py](../../tests/test_web_revocation.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/test_web_sessions.py](../../tests/test_web_sessions.py) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/web/chat-app.test.mjs](../../tests/web/chat-app.test.mjs) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |
| [tests/web/client.test.mjs](../../tests/web/client.test.mjs) | 测试与夹具 | 保留/必要修正；语法/静态检查；全套回归执行 |

### 删除的源码文件

- `cota/channels/utils/front_generator.py`
- `cota/channels/utils/sw.js`
- `cota/channels/utils/utils.py`
- `cota/utils/http/__init__.py`
- `cota/utils/http/client.py`
- `cota/utils/http/manager.py`
- `cota/utils/parser.py`
- `tests/test_llm.py`

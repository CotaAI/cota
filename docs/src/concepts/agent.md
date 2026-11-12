# Agent：一个 Bot 的配置与资源

Agent 把 Bot 的名称、模型、Skill 目录、Policy、ToolRegistry、知识服务和 Store 组合起来。开发者可以用同一套结构定义个人助理、客服或群助手，再选择命令行、Web 或飞书入口。

## 加载一个 Bot

```python
import asyncio
from cota.agent import Agent
from cota.message.message import Message

async def main():
    agent = Agent.load_from_path("./my_bot")
    try:
        processor = agent.create_processor()
        await processor.handle_message(Message(
            text="你好", sender_id="alice", receiver="bot",
            session_id="alice-demo", message_id="hello-001",
        ))
        print(processor.dst.latest_bot_text())
    finally:
        await agent.cleanup()

asyncio.run(main())
```

此示例会调用配置的模型。`receiver="bot"` 用于触发执行；仅记录输入时可以不指定接收者。服务接入使用 [Application](../deployment/application.md)，由它统一管理输入、执行和关闭。

`Agent.load_from_path(path, store=None)` 依次读取 `agent.yml` 和 `endpoints.yml`，校验 Bot 配置并合并默认值，加载 Policy、Store、模型和用户记忆，建立工具注册表。它创建 Bot 的 `workspace/`，并把存在的 `skills/` 目录交给 Pi 发现。SQLite 相对路径以 Bot 目录解析。

`Agent.deploy` 表达 personal（自己使用，包括个人云服务器）或 service（提供给他人），默认 personal。`Agent.environment` 是解析后的执行绑定：默认 machine，工作目录为 Bot 下的 `files/`；不需要原生工具时显式设 `environment.type: none`。环境绑定不替代应用身份认证，详见 [Agent 配置](../configuration/agent.md)。

## 职责分工

| 对象 | 负责什么 |
| --- | --- |
| Agent | 长期持有配置、模型连接、工具与业务资源 |
| Processor | 接收输入、加载 DST、记录事件、创建本轮 runtime |
| Pi Agent Core | 控制模型调用与工具调用的唯一循环 |
| Cota runtime | 更新 Policy guidance，适配模型和工具，提交执行事件 |
| DST / Store | 推导会话状态、持久化事实、恢复上下文 |
| Application / Channel | 管理并发、身份、会话访问和消息收发 |

Skill 是模型按需阅读的业务资源。读取 Skill 不会创建另一个 Agent，也不会自动执行其中步骤。Tool 是可执行能力；`tools.allow/deny` 控制业务扩展，执行环境控制 Pi 原生工具范围；Policy 提供业务指导，不能绕过工具权限。

## 生命周期

同一 Agent 可以创建多个 Processor；每轮工具通过 `for_execution()` 绑定独立用户视图，底层客户端仍由 Agent 共享管理。不要直接修改共享工具上的用户身份来承载并发请求。

使用完成后显式 `await agent.cleanup()`。它关闭工具注册表拥有的资源，并在工具清理失败时仍尝试关闭去重后的全部 LLM 客户端。由 Application 持有 Agent 时，使用 Application 的生命周期。

实现入口：`cota/agent.py`、`cota/processor.py`、`cota/application.py`。

相关文档：[配置总览](../configuration/overview.md) · [执行流程](execution-flow.md) · [Pi runtime](pi-runtime.md) · [Tool 适配](tool-adapters.md)

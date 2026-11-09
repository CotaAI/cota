# LLM：模型服务适配

Pi 控制何时调用模型，Cota 的 `LLM` 负责把请求交给配置的服务。对话、Policy、知识和上下文摘要可以复用同一个模型接口；其中 Policy 和摘要调用不建立第二套 Agent 执行循环。

## 配置与调用契约

在 `endpoints.yml` 的 `llms` 下定义命名模型，在 `agent.yml` 中用 `dialogue.llm` 选择。未指定名称时，Agent 使用配置中的第一个模型。每个模型都必须显式提供非空 `key`、`apibase`、`model`；不解析 `${ENV_VAR}`，也不要求设置 `COTA_API_KEY`。

`LLM.generate_chat()` 接收 `messages`、`max_tokens`、`response_format`、`tools`、`tool_choice`，以及可选 `temperature`。统一返回至少包含 `content` 的字典，工具请求使用 OpenAI 风格的 `tool_calls`。Pi 适配层把这些响应转换为本轮 assistant message。

| `type` | 实现行为 |
| --- | --- |
| `openai`（默认） | 调用 OpenAI 兼容 chat completions；支持可选 `thinking` |
| `openai-rag` | 增加服务端 retrieval 工具；需要 `knowledge_id`，可选 `rag_prompt` |
| `custom` | POST 到完整 `apibase` URL；附加配置进入 JSON 请求体，响应需符合统一格式 |

`openai-rag` 的 retrieval 依赖服务商支持该扩展，并非所有 OpenAI 兼容服务均可用。模型服务必须支持 Bot 使用的 function calling；仅能返回文本的服务不能完成工具任务。

## 资源和诊断

模型观察层为调用关联目的、请求标识和耗时。执行事实引用模型来源；启用 debug 时，原始请求/响应写入独立诊断存储。公开聊天接口不直接返回这些数据。

独立创建 LLM 后显式 `await llm.close()`；使用 Agent 时由 `await agent.cleanup()` 统一关闭。OpenAI 客户端和 custom HTTP session 都有关闭实现。

实现入口：`cota/llm/llm.py`、`cota/llm/factory.py`、`cota/llm/openai.py`、`cota/llm/custom.py`、`cota/llm/observation.py`。

相关文档：[Endpoints 配置](../configuration/endpoints.md) · [Agent](agent.md) · [Pi runtime](pi-runtime.md)

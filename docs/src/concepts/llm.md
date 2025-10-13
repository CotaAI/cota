在多轮对话系统中，LLM扮演着核心角色。

* 处理和理解复杂的对话历史，根据上下文生成连贯且相关的回复。
* 理解对话历史，维护对话状态
* 理解用户意图和对话立即，进行规划和决策

## LLM的配置

类型（Type）：指定LLM的类型，例如“openai”表示使用OpenAI提供的模型。
模型（Model）：选择具体的语言模型，如GPT-3.5、GPT-4等。
API类型（API Type）：指定使用的API类型，例如“openai”表示使用OpenAI的API。
API密钥（API Key）：用于身份验证的API密钥，确保安全访问。
API基础URL（API Base URL）：API的访问地址，用于指定服务器的具体位置。
通过这些配置，可以灵活地调整LLM的行为，以满足不同的业务需求。

## LLM与Agent的关系
LLM作为Agent的核心组件之一，为其提供了语言理解和生成的能力。通过结合其他模块（如决策模块、知识库等），Agent可以完成更复杂的任务，如客户服务、内容创作等。

## LLM与Action的关系
* LLM 参与 决策下一步执行的Action：LLM 可以根据对话历史和上下文，进行分析和决策。Agent 可以利用LLM的分析内容来决定执行哪些 Action。
* Action 依赖 LLM：Action 的执行依赖  LLM 的支持来完成，例如Response的执行，依赖LLM的语言生成能力、Selector的执行依赖LLM的上下文理解和规划决策能力。

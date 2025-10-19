# LLM (大语言模型)

在COTA框架中，LLM（Large Language Model）扮演着核心角色，为智能体提供自然语言理解、生成和推理能力。LLM是Agent智能化的关键驱动力，负责处理复杂的对话理解、决策推理和内容生成任务。

## 🎯 核心功能

### 1. 自然语言理解
- **意图识别**: 理解用户输入的真实意图和需求
- **上下文理解**: 基于多轮对话历史理解当前语境
- **语义解析**: 提取关键信息和实体，支持槽位填充

### 2. 智能决策推理
- **动作选择**: 通过Selector动作，智能选择下一步执行的Action
- **思维链生成**: 产生可解释的推理过程（Chain of Thought）
- **策略学习**: 基于历史数据和标注示例进行策略优化

### 3. 内容生成
- **对话回复**: 生成自然、连贯、符合角色设定的回复内容
- **多模态输出**: 支持文本、JSON等多种格式的结构化输出
- **个性化表达**: 根据Agent角色定制语言风格和表达方式

## 🔧 LLM配置

LLM在COTA中通过`endpoints.yml`进行配置，支持多种模型类型和灵活的参数设置。

### 基础配置结构

```yaml
# endpoints.yml
llms:
  model_name:            # 自定义模型名称，在agent.yml中引用
    type: openai         # LLM类型
    model: gpt-4         # 具体模型名称
    key: your_api_key    # API密钥
    apibase: https://api.openai.com/v1  # API基础URL
    max_tokens: 1000     # 最大生成长度（可选）
    temperature: 0.7     # 生成温度（可选）
```

### 支持的LLM类型

#### 1. OpenAI兼容接口
```yaml
llms:
  gpt4:
    type: openai
    model: gpt-4
    key: sk-xxx
    apibase: https://api.openai.com/v1
    
  deepseek:
    type: openai
    model: deepseek-chat
    key: sk-xxx
    apibase: https://api.deepseek.com/v1
    
  qwen:
    type: openai  
    model: qwen-max
    key: sk-xxx
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
```

#### 2. RAG增强模型
```yaml
llms:
  rag-glm4:
    type: openai-rag
    model: glm-4
    key: your_api_key
    apibase: https://open.bigmodel.cn/api/paas/v4/
    knowledge_id: your_knowledge_id
    rag_prompt: |
      基于知识库内容回答问题。如果知识库中没有相关信息，请明确告知用户。
```

#### 3. 自定义LLM
```yaml
llms:
  custom_model:
    type: custom
    model: your-custom-model
    endpoint: https://your-api.com/v1/chat
    headers:
      Authorization: Bearer your_token
      Content-Type: application/json
```

### 高级配置选项

```yaml
llms:
  advanced_model:
    type: openai
    model: gpt-4
    key: sk-xxx
    apibase: https://api.openai.com/v1
    
    # 生成参数
    max_tokens: 1500
    temperature: 0.7
    top_p: 0.9
    frequency_penalty: 0.1
    presence_penalty: 0.1
    
    # 重试配置
    retry_attempts: 3
    retry_delay: 1.0
    timeout: 30
    
    # 并发配置
    max_concurrent: 10
```

## 🔄 LLM与其他组件的关系

### 与Agent的关系
- **核心驱动**: LLM为Agent提供语言理解和生成的核心能力
- **多实例管理**: Agent可以管理多个LLM实例，针对不同场景使用不同模型
- **动态选择**: 根据Action类型和业务需求，动态选择最合适的LLM

### 与Action的关系

#### BotUtter动作
- **内容生成**: LLM根据prompt模板和上下文信息生成回复
- **思维链**: 生成包含推理过程的structured输出
- **知识集成**: 结合RAG模式，集成外部知识库内容

#### Selector动作  
- **决策推理**: LLM分析对话状态，选择下一个最合适的Action
- **策略学习**: 基于历史策略数据，学习最佳决策模式
- **上下文感知**: 充分利用对话历史进行智能决策

#### Form动作
- **槽位更新**: 智能解析用户输入，更新槽位状态
- **信息提取**: 从自然语言中提取结构化信息
- **用户引导**: 生成合适的询问，引导用户提供必要信息

#### UserUtter动作（代理模式）
- **用户模拟**: 在代理模式下，LLM模拟真实用户的对话行为
- **角色扮演**: 根据设定的用户角色，生成符合特征的输入
- **对话推进**: 自动推进对话进程，用于测试和数据生成

### 与DPL的关系
- **策略执行**: DPL调用LLM执行具体的推理和生成任务
- **思维链生成**: LLM为DPL提供可解释的推理过程
- **策略优化**: 基于LLM的输出质量，不断优化DPL策略

## ⚡ 性能优化

### 1. 模型选择策略
```yaml
# 根据任务复杂度选择不同模型
llms:
  fast_model:      # 简单任务使用快速模型
    type: openai
    model: gpt-3.5-turbo
    
  smart_model:     # 复杂推理使用强力模型
    type: openai  
    model: gpt-4
    
  local_model:     # 高频任务使用本地模型
    type: custom
    endpoint: http://localhost:8000/v1/chat
```

### 2. 并发控制
```yaml
llms:
  production_model:
    type: openai
    model: gpt-4
    key: sk-xxx
    max_concurrent: 20    # 最大并发请求数
    rate_limit: 100       # 每分钟最大请求数
    batch_size: 10        # 批处理大小
```

### 3. 缓存机制
- **请求缓存**: 相同输入的LLM请求结果缓存
- **模板缓存**: 编译后的prompt模板缓存
- **会话缓存**: 会话级别的上下文缓存

### 4. 错误处理
```python
# 自动重试和降级策略
llms:
  primary_model:
    type: openai
    model: gpt-4
    retry_attempts: 3
    fallback_model: gpt-3.5-turbo
    
  backup_model:
    type: openai  
    model: gpt-3.5-turbo
```

## 🚀 最佳实践

### 1. 模型配置建议
- **开发环境**: 使用成本较低的模型（如GPT-3.5）进行开发调试
- **生产环境**: 根据业务需求选择合适的模型，平衡性能和成本
- **专用场景**: 为特定任务配置专门优化的模型

### 2. Prompt工程
- **明确指令**: 在Action的prompt中给出明确、具体的指令
- **格式约束**: 严格定义输出格式，确保系统能正确解析
- **上下文控制**: 合理利用DST提供的状态变量，避免冗余信息

### 3. 安全性考虑
- **密钥管理**: 使用环境变量或密钥管理系统存储API密钥
- **访问控制**: 限制LLM的访问权限，避免滥用
- **内容过滤**: 实施输入输出内容过滤，确保合规性

### 4. 监控和调试
```python
# 启用LLM调试日志
import logging
logging.getLogger('cota.llm').setLevel(logging.DEBUG)

# 监控LLM性能指标
- 响应时间
- 成功率  
- Token消耗
- 错误分布
```

## 🔍 故障排查

### 常见问题

1. **API密钥错误**
   - 检查密钥格式和有效性
   - 确认密钥权限和额度

2. **网络连接超时**
   - 调整timeout参数
   - 检查网络连接和代理设置

3. **模型输出格式错误**
   - 优化prompt模板
   - 增加格式校验和重试机制

4. **性能问题**
   - 调整并发参数
   - 启用缓存机制
   - 考虑使用更快的模型

通过合理配置和使用LLM，可以构建出智能、高效、稳定的对话系统，为用户提供优质的交互体验。

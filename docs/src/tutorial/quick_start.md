## 快捷创建智能体

cota提供了多个场景的智能体示例，方便测试和参考

```bash
cota init
```

执行上面初始化命令后，得到cota_projects目录，cota_projects中的每个目录都是一个智能体示例：
- **weather**: 天气查询机器人，展示基础配置和Chain of Thought推理过程
- **pet**: 宠物问诊机器人，展示代理用户模式（proxy user）和数据生成功能

## 文件说明

每个智能体至少包括`endpoints.yml`和`agent.yml`两个配置文件。

`endpoints.yml` 定义agent运行需要的服务配置，包括数据库类型及配置（用于维护对话状态）、通道类型及配置、大语言模型配置等。
`agent.yml` 定义了agent的基本元素，包括智能体的系统描述、可执行动作、对话配置和策略配置等。

## 运行智能体

选择cota_projects中的文件夹进入，如weather示例：

```bash
cd cota_projects/weather
```

### 配置LLM

编辑`endpoints.yml`文件，配置您的LLM API密钥：

```yml
llms:
  deepseek:
    type: openai
    model: deepseek-chat
    key: your_actual_api_key_here  # 替换为您的真实API密钥
    apibase: https://api.deepseek.com/v1
```

### 启动调试模式

使用命令行与智能体交互，适用于调试和验证：
```bash
cota shell --debug
```

### 启动服务模式

如果需要部署到生产环境提供API服务：
```bash
# WebSocket服务
cota run --channel=websocket --host=0.0.0.0 --port=5005

# 或启动HTTP API服务器
cota server --host=0.0.0.0 --port=8000
```

> 💡 **提示**：初次测试建议使用Memory存储类型，生产环境推荐配置数据库以获得更好的性能和可靠性。

# 实践 1：把天气能力拆成 Skill、工具与 Policy

从 `cota init` 创建的 weather Bot 开始：

1. `skills/weather/SKILL.md` 定义天气业务名称、操作流程、缺失信息和结果判断。
2. `agent.yml` 通过 `tools.allow: [http_request]` 允许查询能力；部署层负责凭证、网络与授权。
3. `policy/*.yml` 保存运营编写或从真实对话修改的教学示例。

```yaml
policies:
  - name: 比较城市天气
    steps:
      - user: 比较一下北京和上海的天气
      - bot:
          - thought: 两个城市已经明确，使用天气能力分别查询。
          - skills: [weather]
          - thought: |
              根据实际结果比较，说明数据来源和时间。
              缺失字段不能当成零值，查询失败要明确告知。
```

Bot 内有序的 thought 可以分别指导能力选择、执行结果处理和话术。Cota 在每次模型请求中提供预算内的完整示例，模型结合当前真实情况判断适用性。Policy 不是强制工作流或精确语义路由器。

测试普通查询、城市缺失、多城市比较、HTTP 错误及新会话隔离。检查 Trace 中的 Skill 读取、调用参数、工具结果和回复；用 Debug request/preparation 核对实际 Policy/thought；有读取记录不代表任务已完成。

改进时可以直接编写新示例，也可以 export 真实对话、人工修改后 import。主文件始终采用同一格式，不另存来源或标注版本，也不写回会话，详见 [对话标注与 Policy](../../concepts/skill-policy.md)。

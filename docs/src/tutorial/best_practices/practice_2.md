# 实践 2：用示例 Bot 验证 Pi 执行链路

Cota 仅分发 `weather` 示例，用于入门和回归测试，覆盖业务规则与追问、Skill、工具调用和多轮对话评测。

## 创建和运行

执行 `cota init`，在 `cota_projects/weather/endpoints.yml` 直接填写模型服务的 key、apibase 和 model，然后运行：

```bash
cota shell --config cota_projects/weather
```

`weather` 组合天气查询、活动查询和出行规划能力。真实用户通过正常消息入口交互，Pi 执行对话循环，模型直接回复问题，每轮正常完成，Cota DST 与 SQLite Store 保存历史和检查点。

## 配置分工

- `agent.yml` 定义角色、规则、模型引用、Pi 参数和工具权限。
- `endpoints.yml` 定义模型服务和 Store。模型 key/model/apibase 直接使用配置文件中的值。
- `policy/*.yml` 定义 policies/name/steps 案例，Bot 内以有序列表表达 thought、skills、result、reply。每次模型请求提供预算内完整示例，模型结合真实上下文判断；默认 all 会优先考虑当前上下文保留的成功读取所关联案例；其它策略使用其各自的检索或判断方法。
- `skills/<name>/SKILL.md` 定义可复用操作流程。Pi 只发现该 Bot 的 Skill，向模型展示目录，模型通过 `read(path)` 按需读取正文。weather 使用 Bot 允许的 `http_request`。

成功读取文档会保存带 resource 元数据的工具结果并更新最近读取标签。标签在追问和完成回复后保留，不改变权限或自动注入正文；完整工具事实位于 Store events；context_messages 是供 Pi 使用的投影，可能已经压缩。

SQLite 相对路径以 Bot 目录为基准。不要分享 `workspace/`、数据库、日志和凭证。

## 可重复的集成测试

在仓库开发环境执行：

```bash
python -m pytest tests/test_bot_templates.py tests/integration/test_example_bots.py -q
```

测试复制并加载 weather 示例及测试专用的对话配置，运行真实 Pi 子进程、OpenAI 客户端、工具与 SQLite。在外部 HTTP 边界提供固定响应，无需真实 API Key。
覆盖模板初始化不覆盖已有文件、配置解析、业务案例注入、对话隔离、追问、重启恢复、HTTP 错误及禁止工具的拦截。

固定模型响应验证的是程序行为，不是模型能否正确理解每一种说法。实际模型效果需要再用自己的模型服务测试。手工场景见生成的 weather README。

## 升级旧示例

旧 动作配置会被新配置校验拒绝。保留有用的业务规则，迁移到 `agent.yml` 和 policies/name/steps 格式的 `policy/*.yml`；操作步骤放入 SKILL.md，实际能力通过 ToolRegistry 或 MCP 注册。

浏览器、桌面和闲鱼示例还依赖缺失的能力适配，因此没有继续作为可运行模板分发。仅改一个 runtime 字段不能使它们恢复工作。

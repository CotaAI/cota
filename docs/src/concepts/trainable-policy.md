# Policy 检索与运行

Cota 的业务策略以文件交付。`policy/POLICY.md` 声明用途和案例，加载 Bot 时建立内存 BM25 索引，通过 `policy_guidance` 工具提供给模型。当前不使用训练命令、Embedding 产物或自动 Policy 选择器。

## 生命周期

1. 编写或审核 Policy，使用对话案例表达 thought、skills、result、reply。
2. 重新加载 Bot；Cota 读取文件，校验案例并建立索引。
3. Pi 中的模型根据当前用户需求决定是否调用 `policy_guidance`，传入具体场景。
4. 检索返回带明确示例边界的完整案例，以及 `details.hits` 实际返回数量。
5. Pi 结合真实执行证据决定是否参考；Cota 保存工具调用、结果与回复。

检索排名表示词项相关性，不表示案例前提已经满足。用户改变目标后，旧案例不能成为继续旧任务的授权；接口失败也不能用案例中的成功结果补齐。

## 上下文与恢复

当前 run 保留完整检索结果，支持后续多次模型决策。跨 run 的请求投影可将旧结果替换为查询和数量摘要；完整结果仍在 Store，可用于 Debug、Trace 和回溯。恢复只重放事实，不会自动重新检索或调用模型。

Policy 结果是普通 `tool_result`，无需单独的标注 Event 或 `llm.policy` 注入记录。Knowledge 的 `search_knowledge` 沿用相同记录方式，辅助重排模型标记为 knowledge 用途，不覆盖主对话决策来源。

## 验证策略效果

使用同一组 `policy/eval/` 案例比较不同 Bot 文件版本，检查能力选择、用户取消和改口、异常分支、回复事实性、工具调用数量及耗时。合同测试验证保存与恢复，不代替真实模型效果评测。

实现入口：`cota/policy/index.py`、`cota/policy/tool.py`、`cota/runtime/pi_runtime.py`。

相关文档：[Policy 配置](../configuration/policy.md) · [对话标注](skill-policy.md) · [Bot 评测](../development/evaluation.md)

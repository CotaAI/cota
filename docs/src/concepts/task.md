# 任务与多 Skill 组合

一次用户任务可以在同一个 Pi 模型—工具循环中读取多份 Skill、调用多个工具并整合结果。Skill 是业务说明，不是独立 Agent；阅读它不会自动执行步骤或开启另一套循环。

例如“比较两个城市的天气并给出出行建议”：模型读取天气 Skill，补齐城市信息，分别调用天气工具，再结合出行 Skill 的说明组织回复。工具权限由 Bot 的 ToolRegistry 决定，不能通过多读一份 Skill 获得额外权限。

## 业务案例如何表达

Policy 的业务标注使用 `policies` 列表，每条以 `name` 命名、以 `steps` 描述案例。Bot 步骤内的 `thought`、`skills`、`result`、`reply` 是有序内容，可以表达能力选择、组合次序、结果判断和回复方式。它们给当前模型提供业务 guidance，不是强制执行的 DAG。

缺少用户信息时，模型直接回复问题，本轮正常完成。后续输入在同一 `session_id` 开始新的 run，继续使用已保存上下文。任务中途读到的 Skill 用读取证据记录，`active_skill` 仅表示最近阅读标签。

## 任务与后台作业

这里的用户任务不等于 `SchedulerJob`。定时任务由独立 SchedulerService 后端管理，供可信应用代码使用；模型没有内置定时或后台任务工具。Application 的并发执行队列也不是定时任务调度器。

当前配置没有旧 `Task` / `task.yml` DAG 编排接口。跨 Agent 的依赖、失败恢复和结果汇总需要由应用层显式管理。

实现入口：`cota/runtime/pi_runtime.py`、`cota/policy/catalog.py`、`cota/executor/scheduler/service.py`。

相关文档：[Skill Policy](skill-policy.md) · [执行流程](execution-flow.md) · [Scheduler](../components/scheduler.md) · [Application](../deployment/application.md)

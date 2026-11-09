# Scheduler：本地定时与后台作业

SchedulerService 保存作业并在到期时调用应用提供的异步 callback。它是供可信应用代码使用的后端设施，默认不向模型注册定时或后台任务工具。

Application / ChannelRunner 的执行排队负责聊天并发，与这里的定时 SchedulerService 是不同机制。后端 callback 与多人会话的可靠投递链路需要应用显式集成。

## 作业模型

`SchedulerJob` 包含 `id`、`name`、`user_id`、`session_id`、`payload`、`enabled` 和调度状态。`ScheduleConfig` 支持三种形式：

| 类型 | 参数 | 含义 |
| --- | --- | --- |
| `at` | `at` | 未来 ISO 时间或 `+5m` 等相对时间，一次执行 |
| `every` | `every_seconds` | 正数秒间隔 |
| `cron` | `expr`、可选 `tz` | cron 表达式和 IANA 时区 |

相对 `at` 在创建时解析为绝对时间，避免重启重新计算。服务校验未来时间、正有限间隔、cron 表达式和时区；不带时区的时间按 UTC 处理。一次性或 `delete_after_run` 作业在触发时从存储移除。

```python
from cota.executor.scheduler.service import SchedulerService

async def on_job(job):
    print(job.payload)

service = SchedulerService(store_path="/tmp/demo-jobs.json")
service.set_callback(on_job)
await service.start()
try:
    # 由可信应用创建、查询和更新作业。
    pass
finally:
    await service.stop()
```

此片段只展示资源生命周期，不创建任务，也不会调用模型。

## 先保存，再执行 callback

每次触发先预约该作业的执行位置，持久化下一次时间、次数或删除状态，然后创建 callback task。持久化失败不创建 callback，也释放预约。JobStore 的更新使用脱离缓存的候选对象和原子文件替换，失败不能污染内存中的已提交状态。

同一 job 不并行执行 callback；全局并发默认最多 5 个。callback 不阻塞 tick 循环，完成状态只合并回仍存在的作业，避免覆盖用户期间修改的其他字段。`stop()` 取消并等待服务与 callback 任务。

这一顺序避免未提交的触发执行外部操作，但不提供外部副作用的 exactly-once 保证：持久化后进程崩溃可能尚未运行 callback。业务 callback 应根据任务特点自行设计幂等和补偿。

## pre_check

本地 watcher 可以配置 `pre_check`，执行轻量命令并从输出 JSON 的 `has_new` 判断是否触发完整 callback。可用 `state_file` 去重；没有变化时不请求模型。命令属于可信本地部署能力，不是多人服务沙箱。取消或超时会回收其进程组；旧 `trigger_job_name` 配置已拒绝。

作业创建成功不等于完成或通知送达。

实现入口：`cota/executor/scheduler/service.py`、`cota/executor/scheduler/store.py`、`cota/executor/scheduler/types.py`、`cota/__main__.py`。

相关文档：[任务](../concepts/task.md) · [CLI](../deployment/cli.md) · [可靠投递](../deployment/delivery.md) · [Tool 适配](../concepts/tool-adapters.md)

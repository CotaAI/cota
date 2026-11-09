# Cota 测试与代码检查

源码开发使用 Python 3.12+ 和 Node.js 22.19+（仓库固定版本见 `.node-version`）。

```bash
python -m pip install -e '.[dev,feishu]'
npm ci --prefix cota/runtime/pi
python scripts/check.py --coverage
```

安装依赖需要网络；测试不需要模型密钥，不调用真实 LLM、天气接口或飞书服务。
集成测试会启动本地 Node/Pi、MCP 子进程以及 localhost 随机端口 HTTP/WebSocket 服务；
沙箱必须允许子进程和本地监听。飞书额外依赖用于验证 SDK 事件解析，不发送飞书消息。

`scripts/check.py` 依次执行：

1. 所有第一方 Python AST、JavaScript/ES module `node --check`、Shell `bash -n`。
2. Ruff 的 `F` / `E9`：未定义名称、无用导入、语法等实质错误；不强制整仓格式改写。
3. Pytest，包含真实 Pi 循环、SQLite、HTTP/WS 的集成合同测试。
4. Node 测试：Pi worker、Web SDK、聊天页面、Debug viewer。

任何一步失败都会返回非零状态，不会把未执行的后续检查当作通过。
`--coverage` 产出 `coverage.json` / `coverage.xml`，统计 Python 语句与分支，最低门槛为审计前的 **76%**。
这个门槛用于防止整体退化，不代表重要模块只要达到比例就合格；JS 行覆盖率不包含在该数字里。
CI 配置在 `.github/workflows/tests.yml`，与本地使用同一个入口。

## 开发时如何选择测试

快速静态检查：

```bash
python scripts/check.py --static-only
```

修改期间运行相关用例，再在结束前跑全套：

```bash
python -m pytest -q tests/test_dst_invariants.py tests/test_store.py tests/test_persistence_contract.py
python -m pytest -q tests/test_trace_runtime.py tests/test_pi_runtime.py
python -m pytest -q tests/test_channel_audit.py tests/test_web_app_integration.py
python -m pytest -q tests/executor tests/scheduler
node --test tests/web/*.test.mjs tests/debug/*.test.mjs
```

也可使用 `python scripts/check.py --tests tests/test_trace_runtime.py`：保留全仓静态和 JS 检查，只缩小 Python 用例范围。
覆盖率门槛只对全套运行启用，不接受局部测试加 `--coverage`。

## 按行为补测试

| 修改位置 | 必须考虑的合同与对应测试 |
| --- | --- |
| DST / Event / Store | 正常执行和重放一致、快照后追加、冲突、提交失败、跨会话隔离；`test_dst_invariants`、`test_persistence_contract`、`test_runtime_persistence`、`test_store`、`test_read_isolation` |
| Pi bridge / Trace | 模型原始参数与转换后实参、先保存再副作用、batch follower 引用、数值跨 JS 往返、取消与恢复；`test_trace_runtime`、`test_pi_runtime`、`test_tool_event_contract` |
| Policy | 标注解析、训练产物加载、推理检索、预算、按执行结果指导；`test_skill_policy*`、`test_trainable_policy`、`test_annotation*` |
| Evaluation | 验证要求隔离、逐项判定与证据校验、HTTP content 正文、进度/等待/取消、独立案例、重评与比较；`test_evaluation`、`integration/test_example_bots` |
| Application / Web | 两用户并发、同会话顺序、重复输入、重连、撤权、慢连接隔离、关闭中的认证/回放；`test_web*`、`test_channel_audit`、`test_channel_scheduling` |
| 群聊 | 只记录不触发、身份上下文、主动回复节流和相关性；`test_group*`、`test_proactive_quality` |
| LLM / Knowledge | 使用实际包装类的签名、仅工具响应、温度参数、资源关闭；`llm/test_client_contract`、`test_execution_logging` |
| MCP / 工具 | 同任务 enter/exit、取消、token 更新、原始返回类型、公共 HTTP 地址和跳转约束；`executor/test_mcp_lifecycle`、`executor/test_audit_security` |
| Memory | 用户隔离、保留连接配置不写入事件或 prompt；`test_memory_context_boundary`、`executor/test_user_memory` |
| Scheduler | 用户归属、重复触发、忙碌占位、持久化失败、运行中更新、关闭；`scheduler/test_service_regressions`、`scheduler/test_atomic_updates` |
| CLI / 包分发 | 退出清理、TLS、隧道进程、定时消息统一入口、init 不复制部署数据；`test_cli_lifecycle`、`test_cli_scheduler`、`test_bot_templates`、`test_debug_shell` |

新增或修复行为时，优先加入一个能在旧代码上失败的复现，再修改实现。
测试应断言用户可见行为和持久化合同，而不是复制实现计算同一个结果。
不要通过删断言、扩大 mock 范围或跳过集成用例来消除回归。

官方仅分发 `bots/weather`；`tests/fixtures/bots` 中的 hello/pet 仅服务于聊天隔离、禁止工具、业务追问与取消的集成测试，不进入发行包或 `cota init`。

共享 `mock_agent` fixture 提供临时 Skill 目录、独立 workspace、实际 ToolRegistry 和模拟模型。
状态/协议测试应尽量保留真实 Pi、Store 和队列，只替换外部模型/网络边界；
配置、LLM adapter 与资源生命周期测试使用真实包装类，避免 mock 隐藏参数不兼容。
每个测试使用独立临时数据目录；显式 await 异步调用，关闭 Agent、服务与连接。
未等待协程和对象销毁时的异常会作为失败处理。

## 验证边界

SQLite、内存 Store、真实本地 Pi/MCP 与 WebSocket 流程由本地测试覆盖。
MySQL/PostgreSQL 隔离设置有合同测试，但还需实际数据库环境验证；飞书投递、真实模型质量、
公网隧道、非 POSIX stdin fallback，以及四个平台发布包的运行应在相应环境验证。
发布包另由 `.github/workflows/runtime-wheels.yml` 构建并执行离线安装冒烟测试。
此次审计没有以覆盖率代替这些验证，也没有声称已经实际运行新增 GitHub Actions。

## 天气与出行业务验证

`bots/weather/policy/eval/data.yml` 是随 Bot 交付的30个案例、43轮对话验证（94条要求）。统一命令执行指定 Bot，并使用 LLM Judge 逐条评判：

```bash
cota eval --config /path/to/configured-bot --output /tmp/weather-evaluation-1
python -m pytest tests/test_evaluation.py tests/integration/test_example_bots.py tests/test_bot_templates.py -q
```

第一条需要真实模型配置，会产生模型费用，并可能执行真实 HTTP/工具，不属于默认 CI。第二条不访问真实模型或天气接口，检查格式、评委输出校验、隔离执行、报告、重评、对比与真实 Pi/Store/模型协议。不要把单测通过数当作真实业务准确率。见[评测说明](../docs/src/development/evaluation.md)。

`test_init_weather_thirty_cases_run_through_eval_cli` 从 init 生成模板，经实际 CLI、Pi 和 SQLite 执行全部43轮，并核验结构化结果及86份逐轮 Trace 文件。模型与评委响应受控，仅验证流水线与产物，不能将测试通过率当作真实模型准确率。

评测进度测试覆盖无参数且未开启 debug 的 CLI 输出、阶段顺序、等待提示及取消后停止提示；工具证据测试构造 Pi 的 result/content 分离形式，确认 HTTP 正文进入评委输入，同时排除 debug 与图片数据。真实模型的失败记录可用 `cota eval judge` 重评，Bot 回答质量和评委判定质量需分别检查。

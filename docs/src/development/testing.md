# 开发与验证

框架代码验证与 Bot 业务效果验证是两件事。前者检查状态、协议和生命周期，后者检查真实模型是否正确理解业务并遵守规则。

## 开发环境与统一检查

在仓库根目录、Python 3.12+ 虚拟环境中：

```bash
uv pip install -e '.[dev,feishu]'
npm ci --prefix cota/runtime/pi
python scripts/check.py --coverage
```

Node.js 至少 22.19，固定版本见 `.node-version`。统一入口依次检查第一方 Python/JS/Shell 语法、Ruff、Python 回归和 Node 测试；失败返回非零状态。
覆盖率统计包括 Python 语句与分支，输出 coverage.json/coverage.xml；JS 测试单独执行，不算入该数字。
最低覆盖率门槛用于防止整体退化，不代表重要行为达到比例即可。

测试使用临时目录、模拟模型和外部网络边界，包含真实本地 Pi、SQLite、MCP SDK 和 HTTP/WebSocket 交互。
不需要模型密钥，但需要允许创建子进程和监听 localhost 随机端口。
不会通过这些测试推定真实飞书权限、生产数据库或模型业务质量已经验证。

绘本复杂流程示例位于 [bots/picture-book](https://github.com/CotaAI/cota/tree/main/bots/picture-book)：复用 Pi 原生工具，独立连接图片生成/编辑与视觉接口，再制作中文 PDF。`tests/test_picture_book_bot.py` 覆盖协议、资产复用、PDF 留白与渲染、限时下载、真实 Pi 多步执行与 SQLite 恢复、WebSocket 历史。PDF 相关用例需要该 Bot 的可选 requirements、Poppler 和中文 TrueType 字体；缺少时明确跳过。实际创作质量需要另行配置模型、逐页审校；reply-review 不代替图像质量评测。

## 修改时选取测试

```bash
python scripts/check.py --static-only
python -m pytest -q tests/test_dst_invariants.py tests/test_persistence_contract.py
python -m pytest -q tests/test_trace_runtime.py tests/test_pi_runtime.py
python -m pytest -q tests/test_channel_audit.py tests/test_web_app_integration.py
python -m pytest -q tests/executor tests/scheduler
python -m pytest -q tests/test_evaluation.py tests/test_bot_templates.py tests/integration/test_example_bots.py
node --test tests/web/*.test.mjs tests/debug/*.test.mjs
```

修复缺陷先加入能复现失败的测试，再修改实现。保留真实的状态/协议层，只在模型、网络等外部边界替换响应；避免用过大的 mock 掩盖签名、取消或持久化问题。
异步调用必须 await，服务和连接显式清理。未等待协程和 unraisable 异常会导致测试失败。
仓库 `tests/README.md` 提供按模块选择测试的详细表；`.github/workflows/tests.yml` 使用同一检查入口。

## 验证一个 Bot

```bash
cota shell --config ./my-bot --debug
```

准备代表性输入：普通问题、缺失信息、取消/改口、不同结果分支、接口异常、越权能力请求和多用户/群聊场景。
逐项查看实际 Skill 读取、工具参数与结果、业务回复，以及 request 中的 Policy guidance。

用同一批问题比较 Bot 文件版本，记录任务完成、事实性、异常处理、延迟和成本。工具读取或案例注入成功本身不是任务成功。
可以使用 `cota eval --config ./my-bot` 执行 policy/eval 中的对话验证，由 LLM 逐条评判，并使用 eval judge/compare 复核和比较。见[对话评测](evaluation.md)。当前没有自动修改或应用 Bot 版本的 RSI 功能。

评测开发还需覆盖：无 debug 的 CLI 进度、长请求等待提示与取消后的任务清理、重评仅进入评判阶段，以及 Pi 工具 result 只有元数据时仍把 content 文本正文交给评委。进度通知属于评测观察接口，不写入运行 Event。对应测试见 tests/test_evaluation.py。

真实模型验证同时检查业务事实与表达质量，例如是否主动推荐超预算项目、是否把内部流程写进回复。把模型问题与评委误判分别复核，不通过放宽验证要求或只挑通过结果来报告优化成功。

## 文档构建

```bash
mdbook build docs --dest-dir /tmp/cota-doc-book
```

文档目录由 SUMMARY.md 管理。新增页面需加入目录并检查相对链接；配置例子应与 validator 和真实模板一致。
Pages 工作流使用固定 mdBook 版本构建，再把 docs/landing.html 作为站点首页。手册欢迎页使用 introduction.html，避免被站点首页覆盖。
历史 plans/specs/audits 不在当前手册中，它们记录当时的设计与验证，不是现行 API 契约。

模型接口测试不仅要预设返回 tool_calls，还必须检查真实 HTTP 请求确实包含允许的工具 schema，并覆盖下一轮的保留、更新与撤销。至少一个模拟 provider 应根据收到的 tools 决定是否返回工具调用，避免“请求未声明工具，但测试服务仍强行返回调用”掩盖接入问题。

长任务优化的回归入口：

- `tests/test_store_incremental.py`：无变化 revision 不变、追加不导出/重放历史、规范哈希一致、并发输入与保存等待期间新增事件不丢失、内部事实不可变。
- `tests/test_model_debug_storage.py`：状态更新不重写大正文、适配器请求升级、数据库重开后仍能读取完整诊断。
- `tests/test_execution_progress.py`、`tests/debug/viewer.test.mjs`：阶段查询只读且有界，上限和超时提示准确，旧 run 的迟到结果不覆盖当前阶段。
- `cota/runtime/pi/image-context.test.mjs`、`model.test.mjs`、`tests/test_context_optimization.py`：当前图片批次、重复内容、同路径不同版本、恢复和实际供应商请求；保留原始证据并通过 Pi 原生压缩处理文本压力。
- `tests/test_pi_bridge.py`：本地 SSE 请求超时时，即使诊断回调尚未确认，终止消息仍保留错误类型；测试不调用真实收费接口。

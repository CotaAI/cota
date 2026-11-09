# Bot 对话评测

Cota 用 LLM 逐条评判业务要求。验证文件随 Bot 分享，评测过程独立于运行时和 Policy 训练；没有自动修改或应用 Bot 的 RSI 功能。

## 编写验证文件

在 Bot 的 `policy/eval/` 下建立一个或多个 YAML 文件，可以分子目录。沿用 Policy 的 `policies / name / steps / user / bot` 结构，但 bot 下只接受 `reply-review`：

```yaml
policies:
  - name: 活动预算调整
    steps:
      - user: 杭州，两个大人一个孩子，总门票预算300元，只要室内活动
      - bot:
          reply-review:
            - 按三人计算总费用。
            - 推荐的活动必须符合杭州、室内、可参加和总预算条件。
            - 活动名称和价格与实际查询结果一致。
      - user: 改成100元，其他不变
      - bot:
          reply-review:
            - 保留杭州、三人、室内条件，只调整预算。
            - 没有符合条件的活动时说明原因，不擅自放宽条件。
```

每个 user 后面有一个 bot，列表中的每条要求独立评判、默认等权。不填写标准答案、thought、skills 或 result；第一版不接受权重对象或 skill-review。名称在同一文件内唯一。案例身份为 `相对于验证目录的文件路径::name`，改名或移动文件相当于不同案例。

`policy/*.yml` 是运行指导；`policy/eval/**/*.yml` 是验证要求。训练与运行的 Policy 加载不会递归进入 eval。执行时只发送 user 文本，保留 Bot 的真实回复推进下一轮；要求只交给评委，不作为 Bot 的回复或 prompt。评委只能看到截至当前轮的事实，不看到未来输入。

## 从 init 开始

在准备创建 Bot 的目录中执行：

```bash
cota init
cd cota_projects/weather
```

编辑 `endpoints.yml`，填写 `llms.default` 的 `key`、`apibase`、`model`。可选添加同格式的 `llms.evaluator`；不要创建留空的 evaluator 占位项，否则会按配置错误处理。

```bash
cota eval
# 需要固定输出目录和额外模型诊断时：
cota eval --output workspace/evaluations/baseline --debug
```

新的 weather 模板自带30个案例、43轮输入、94条评测要求。默认 all Policy 不需要训练；选择依赖索引/embedding等训练产物的方法后，先执行 `cota train`。init 跳过已有 Bot，升级代码不会自动覆盖用户已有的 Bot 文件。

## 执行评测

先配置 Bot 的 `endpoints.yml`。评测优先使用 `llms.evaluator`，未配置 evaluator 时使用 `llms.default`；两者配置格式相同。模型选择统一由 endpoints.yml 管理，不需要命令行选择。已配置的 evaluator 若不完整或调用失败，会报告错误，不会静默切换。不同模型不是必需，但可以帮助减少同模型的共同偏差。

```bash
cota eval --config ./my-bot
cota eval --config ./my-bot --output /tmp/eval-before
cota eval --config ./my-bot --cases ./my-bot/policy/eval/basic.yml --repeat 3
cota eval --config ./my-bot --case 'data.yml::budget_change' --debug
```

`--config` 是实际被测 Bot，绝不是只借用模型连接。使用该 Bot 的配置、Skill、Policy、训练产物与资源。若训练产物过期，先运行 `cota train`。

每个案例、每次重复都使用新的临时 Bot 目录、SQLite、用户与会话；同一案例的多轮保持历史。运行目录不含 policy/eval、配置中的历史数据库、日志或 workspace；资源目录里的静态数据库会保留。原 Bot 定义与聊天记录不改动；默认结果写入原 Bot 的 `workspace/evaluations/<run_id>/`，也可以用 `--output` 指定。已有输出目录不会覆盖。

这一版评测 direct 对话，不通过 Channel，不评测群聊触发、鉴权或回复投递。原 workspace 中的历史内容不带入；有必要的静态数据请放在随 Bot 交付的资源目录。绝对的机器 workspace 必须在 Bot 内部，复制后重新绑定，外部 workspace 会拒绝。符号链接资源不支持。复制时不包含 `.venv`、`node_modules` 等本地依赖目录；需要的工具依赖应预先安装在评测环境中。

临时目录不是安全沙箱：personal 的机器工具依然有宿主机权限，HTTP 与外部服务依然真实执行。评测工具有副作用时应使用专用测试服务与凭证。验证目录不会复制给执行 Bot，但 unrestricted personal 工具不能提供对原宿主文件的安全隔离。

默认每轮执行超时300秒、评判120秒，可通过 `--timeout` / `--judge-timeout` 调整。真实天气/活动结果随外部服务变化；没有隐式 mock 或异常注入。条件没有实际发生、证据不足时，评委应给出无法判断，不能把假设条件当作已经验证。

## 进度显示

直接执行 `cota eval` 就有进度，不依赖 `--debug`：启动时显示案例运行数、轮次数、评委与结果目录；随后显示案例序号、重复次数、每轮的 Bot 执行 / LLM 评判阶段与案例结果。长请求每15秒提示仍在等待、本阶段耗时与超时限制，结束显示符合项数和执行/评判错误数。`cota eval judge` 同样显示评判进度。

进度逐行立即写到 stderr，在终端和重定向日志中都可见；最终报告路径写到 stdout。进度不进入 Bot 的 prompt、DST 或评分数据，不打印输入、工具参数或密钥。脚本仍以 results.json 和退出码为准。Python 的 evaluate / rejudge 默认静默，需要监听时可传 `progress=callback`，回调收到当前阶段字典。

## 结果和内部记录

```text
<run_id>/
├── results.json
├── report.md
└── traces/
    ├── 0001-001.execution.json
    ├── 0001-001.judge.json
    └── ...
```

- `report.md`：逐案例、逐轮展示用户输入、实际回复、每条要求的结论、理由和事件证据引用。
- `results.json`：`schema_version: 1`，保存运行ID、时间、Bot文件摘要/版本/模型身份、评委配置摘要/指令版本，以及验证集 suite、机器可读 summary、案例身份、内容摘要、重复次数和逐轮结果。
- `execution.json`：该轮结束时的 DST 与完整事件历史。开启 `--debug` 额外保存已记录的模型请求诊断。
- `judge.json`：Cota 提交给 LLM adapter 的请求参数及返回值，足以复核评测输入，不包含认证头。

### 评委如何获取执行证据

每轮先保存执行 Trace，再将截至当前轮的 user_utter、bot_utter、tool_started、tool_result 和 run_finished 中的业务字段交给评委。评测项和这些记录组合成独立的评判请求；不读取模型隐藏思考，debug 字段和图片二进制不进入当前文本评委。

Pi 工具可能把结构化数据或元数据放在 `tool_result.payload.result`，把实际交给模型的正文放在 `payload.content`。例如 HTTP 的 result 可能只有 status_code，响应 body 在 content 的文本块内。评委同时获得 result 和存在的文本 content，不能只凭状态码验证温度、日期或价格。普通文本结果没有独立 content 时，直接使用 result 中的文本。此逻辑不依赖 debug。

排查疑似误判时，先看 report.md 的评测项、理由与 event_id，再核对 execution.json 的工具正文和 judge.json 的实际评判输入。判断依据应是完整回复与当前评测项；征求调整条件不等于已擅自放宽条件。程序校验输出格式、条数和证据 ID，无法保证评委理由与结论在语义上一定正确。

业务结论为 pass（符合）、fail（不符合）、inconclusive（无法判断），并附简短理由和真实 event_id。程序严格验证条数、编号、结论及证据引用；评委漏评、重复评判、输出损坏、超时均是评委错误，不冒充业务不符合。

运行状态与业务结论分开。Bot 运行失败后，该案例剩余输入不继续执行；其他案例照常执行。评委失败不影响 Bot 后续轮次。没有评判的要求也计入总项数，不能靠丢掉失败轮次提高通过率。

退出码：0 为全部案例、全部要求通过；1 为业务不符合、无法判断或运行/评委不完整；2 为配置/命令/文件错误。分数是符合项数/总项数，无法判断不算通过。LLM 结论不是事实保证，应根据报告中的证据复核关键项。

结果不复制 endpoints 凭证；对话、工具输出和可选 prompt 可能包含业务数据，应按原始 Trace 的要求保管。结果在默认 workspace 下，不随 init 模板交付。

## 重新评判与对比

```bash
# 只使用历史 Trace；不会再次运行 Bot 或工具
cota eval judge --run /tmp/eval-before --config ./my-bot \
  --output /tmp/eval-rejudged

# 同一验证集运行优化后的 Bot
cota eval --config ./my-bot --output /tmp/eval-after

# 支持两个或更多结果，按传入顺序排列，变化比较第一份与最后一份
cota eval compare /tmp/eval-before /tmp/eval-after --output /tmp/eval-comparison
```

修复评委证据提取、修改评委指引或更换评委模型后，可以用 judge 基于原始 Trace 重评，避免重新执行工具；原始 Trace 必须保留必要正文。

重评保留新 run_id 和 source_run_id，不覆盖原结果；校验执行 Trace 摘要，拒绝被更改的记录。重评使用当时保存的验证要求，不读取已修改的新验证文件。要验证新要求，应启动新的评测。

对比同时产生 `comparison.json` 与 `report.md`，按文件路径、name、重复序号对齐，展示逐条变化。案例内容或评委模型/指令变化会标记为不可直接比较；新增/缺失案例也明确列出。相同总分但失败项不同会标记为部分变化。即使案例仍有失败项，某些条目改善且没有条目退步时，也会标记 improved；这不表示案例已全部通过。运行中断或执行/评判超时设置改变也会明确标记不可直接比较。

一次变化不能证明稳定提升；可使用 repeat 多次观察。即使案例和评委一致，外部数据与模型随机性仍会影响结果，不能把所有差异归因于代码修改。

## 脚本调用与 RSI 数据契约

命令无需人工交互；模型与工具照常执行，不是预设回复的业务脚本。结果以 JSON 为事实来源，Markdown 是阅读视图，不需要从文本报告抽取分数。

`results.json` 的关键字段：

| 字段 | 用途 |
| --- | --- |
| schema_version | 结果格式版本，目前为1 |
| run_id / source_run_id | 当前运行及重评来源，不覆盖原运行 |
| suite.hash / cases / turns / criteria | 所选验证集内容摘要及规模；顺序与 repeat 不改变摘要，改案例内容会改变 |
| bot.hash / runtime_hash | Bot定义与模型资源摘要，以及实际 Cota/Pi源代码与锁文件摘要；能识别源码开发时同版本号的代码变化 |
| engine | 当前评测代码摘要、Cota/Python版本；重评使用当前评测实现，bot 保留原执行身份 |
| judge | 实际评委名称、模型配置摘要和指令版本 |
| execution | 重复次数、Bot/评委超时、debug设置 |
| summary | 整体结论、案例/轮次/要求总数、通过与未完成统计 |
| cases[].summary | 单次案例执行的汇总 |
| cases[].turns[] | 用户消息、实际回复、逐条结论与事件证据、Trace路径 |

`summary` 包含：

- `cases_unique`：不重复的案例数量；`case_runs` 包含重复次数。
- `criteria_total / criteria_passed / criteria_failed / criteria_inconclusive / criteria_unjudged`：所有计划评测项均进入分母，跳过/评委错误不会被丢掉。
- `criterion_pass_rate`：符合项数/总项数；`case_pass_rate`：全部要求通过的案例次数/案例总次数。均为0～1的小数。
- `judgement_coverage`：已经给出结论（包括无法判断）的要求占比；不能把覆盖率当作正确率。
- `turns_total / turns_completed / turns_errored / turns_skipped / judge_errors`：区分执行问题、评委问题和业务不符合。
- `verdict`：pass/fail/inconclusive；中断或未完成的运行不会成为成功基线。

`comparison.json` 提供 `comparable`、逐案例 `reasons`、逐项 `change` 和完整证据。原因码包括 `judge_changed`、`case_changed`、`case_missing`、`run_incomplete`、`execution_settings_changed`。同一条件下且所有评测项都有明确结论时，`summary.criterion_pass_rate_delta` 给出最后一份减第一份的通过率变化（0.1 表示提升10个百分点）；否则为 null。少测困难案例不会产生一个虚假的整体提升数值。评测代码变化会额外提示复核；首尾 Bot 摘要相同会提示不要将模型波动或重新评判误认为版本优化。

compare 退出码0表示对比产物已成功生成，不表示 Bot 提升；自动化流程应读取 comparable、delta 和逐项变化。重评只更换评委，不运行工具；这两类命令可以被后续 RSI 调用，但不会自动改写或发布 Bot。

评测存在业务失败时仍要读取报告；例如 shell 脚本可这样处理：

```bash
eval_status=0
cota eval --output workspace/evaluations/baseline || eval_status=$?
if [ "$eval_status" -gt 1 ]; then
  exit "$eval_status"
fi
python - <<'PY'
import json
from pathlib import Path
result = json.loads(Path('workspace/evaluations/baseline/results.json').read_text())
print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
PY
```

首次基线与优化后运行应保留同一验证集；新增案例形成新验证集版本。30个案例同时覆盖条件，但没有强制让网络进入特定故障：只有实际出现且记录下来的分支才有执行证据。重复评测、真实结果复核和独立保留的验证集仍是判断优化质量的必要依据。

## 开发入口与进度接入

| 文件（位于 cota/evaluation/） | 职责 |
| --- | --- |
| schema.py | 验证文件与结果格式、稳定案例 ID、内容摘要 |
| runner.py | 隔离案例执行、逐轮保存、重评、资源清理 |
| judge.py | 业务证据提取、评委提示词、输出及证据引用校验 |
| metrics.py / artifacts.py | 汇总分数、结构化结果、报告与版本对比 |
| provenance.py | Bot 运行与评测代码身份，供复现和比较 |
| progress.py | 可选进度观察、15秒等待通知、阶段结束或取消时清理通知任务 |
| cli.py | 命令参数、终端进度、报告路径与退出码 |

Python 调用默认不打印进度，需要显示时显式传入同步回调：

```python
import asyncio
from cota.evaluation.runner import evaluate

def on_progress(update):
    print(update, flush=True)

result = asyncio.run(evaluate('./my-bot', progress=on_progress))
```

`rejudge(..., progress=on_progress)` 使用相同入口。回调字典的 event 可能为 run_started、case_started、stage_started、heartbeat、turn_finished、case_finished、run_finished；阶段 phase 为 bot 或 judge，案例上下文包含 index、total、case_id、repetition、turns，等待通知还包含 turn、elapsed_seconds 和 timeout_seconds。这里的 event 是进度通知名称，不是 Cota 的运行 Event 类型，不进入 DST/Store。

回调应快速返回；普通回调异常只记日志，不改变评分或执行结果。stage_started/heartbeat 表示正在等待该阶段，不能解释为某个具体工具正在执行。持久产物以 results.json 与 Trace 为准，不依赖回调补建事实。

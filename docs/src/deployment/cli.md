# CLI 命令参考

```bash
cota --version
cota --help
cota run --help
cota shell --help
cota train --help
cota annotate --help
cota eval --help
```

## init

`cota init` 在当前目录创建 cota_projects/weather，跳过已存在的 Bot。
它复制模板，不启动模型；过滤 workspace、数据库、日志、`.cota` 等运行状态，不自动升级旧模板。

## shell / run

```bash
cota shell --config cota_projects/weather --debug
cota run --config cota_projects/weather --chat-app --host 127.0.0.1 --port 5005
```

| 参数 | run | shell | 含义 |
| --- | --- | --- | --- |
| --config | ✓ | ✓ | Bot 目录，默认 ./ |
| --debug | ✓ | ✓ | 采集完整模型诊断和事件日志；shell 另启本地只读页面 |
| --log | ✓ | ✓ | 日志级别，默认 INFO |
| --chat-app | ✓ | | 挂载 /chat/ 配套聊天应用 |
| --host / --port | ✓ | | 默认 0.0.0.0 / 5005 |
| --ssl-cert / --ssl-key | ✓ | | 必须配对提供的 TLS 证书和私钥 |
| --tunnel [类型] | ✓ | | 临时公网通道；默认 localhostrun，可选 cloudflared/ngrok，依赖相应命令 |

通道选择使用 agent.yml/endpoints.yml 的 channels，不使用旧 --channel 参数。
shell 仅支持 direct，输入 `/stop` 退出；没有 --session 参数，每次启动新会话。
完整调试说明见 [Debug](debug.md)。

## train

```bash
cota train --config ./my-bot
cota train --config ./my-bot --check
```

根据 agent.yml 的 policy 方法构建产物，默认 models/policy.json。它不启动 Bot/Store/Pi；BM25/规则等可离线训练，Embedding 会请求向量服务。
`--check` 验证产物与配置/案例是否匹配，不重新训练。缺失、过期或损坏时非零退出。
默认 all 不要求预训练；更新已加载的 Bot 仍需重启或重新加载。详见 [Policy 训练与推理](../concepts/trainable-policy.md)。

## annotate

直接编写 policies/name/steps 不需要数据库。也可以从真实对话整理：

```bash
cota annotate export --config ./my-bot --session SESSION_ID --output review.yml
# 编辑 review.yml：补充或纠正 thought、skills、result、reply
cota annotate import --config ./my-bot --input review.yml --output reviewed.yml
```

export 从持久 SQL Store 读取 user_utter/bot_utter，生成一份待编辑 Policy 草稿。
import 只校验文件格式和预算并写入新文件，不读取或修改会话数据库；没有来源版本或 policy_annotation Event。
手写文件同样可以 import。输出路径必须不存在，命令不会覆盖已有文件。

审核后将结果放入 Bot 的 policy/；训练型策略重新 train，再重新加载 Agent。
Skill 名称在 Pi 发现目录后、首次模型请求前核验，不由 annotate 重新实现 Skill parser。
见 [对话式标注](../concepts/skill-policy.md)。

## eval

在含有 agent.yml、endpoints.yml 的 Bot 目录执行 `cota eval` 即可，不需要必填参数：

```bash
cota eval
# 也可以在其它目录显式选择 Bot 和结果目录
cota eval --config ./my-bot --output /tmp/eval-1
cota eval judge --run /tmp/eval-1 --config ./my-bot --output /tmp/eval-rejudged
cota eval compare /tmp/eval-1 /tmp/eval-2 --output /tmp/eval-comparison
```

默认运行 policy/eval 下所有验证文件，评委优先使用 llms.evaluator，未配置时使用 llms.default；模型选择统一由 endpoints.yml 管理，配置错误不会静默回退。逐条 reply-review 由 LLM 评判，生成统一 JSON、Markdown 报告及执行/评委 Trace。输出目录不得已存在；省略 eval 的 output 时写入 Bot 下的 `workspace/evaluations/<run_id>/`。重评不运行 Bot，compare 不调用模型。详见[Bot 对话评测](../development/evaluation.md)。

| eval 参数 | 默认值 / 含义 |
| --- | --- |
| `--config` | `./`，当前 Bot 目录 |
| `--cases` | Bot 的 `policy/eval/`，可指定文件或目录 |
| `--case` | 仅运行指定的 `文件相对路径::案例name`，可重复提供 |
| `--repeat` | 1，每次使用独立案例状态 |
| `--output` | 新的结果目录；judge 和 compare 必填 |
| `--timeout` | 每轮 Bot 执行300秒 |
| `--judge-timeout` | 每轮评判120秒，eval 和 eval judge 均支持 |
| `--debug` | 额外保存 Bot 模型请求诊断；仅用于执行评测，不启动网页 |
| `--log` | WARNING，不影响默认进度提示 |

进度写入 stderr 并立即刷新；等待中的 Bot/评判请求每15秒提示耗时。报告路径写入 stdout；脚本读取 results.json，无需解析终端文案。不开 debug 也保存执行事件、工具结果、逐项评分及评委请求/响应。

执行与重评的退出码：0 全部通过；1 有不符合、无法判断或执行/评判不完整；2 配置、文件或入口错误。compare 的0只表示对比文件生成成功，是否改进应读取 comparison.json。

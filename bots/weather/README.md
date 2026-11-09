# Weather & Outing Bot

在原天气示例上组合三个 Skill，测试多能力协作和 Policy 分支，不需要额外启动活动服务：

| Skill | 能力 | 数据来源 |
| --- | --- | --- |
| weather | 查询当前天气与16天内逐日预报、地点确认、备用来源 | 真实 HTTP：Open-Meteo / wttr.in |
| activity-search | 按城市、人数、门票预算、亲子和室内外条件筛选 | 同目录 activities.json，全部为虚构测试数据 |
| outing-plan | 组合天气与活动，处理约束变化和部分失败 | 前两者的实际读取结果与用户约束 |

保持 `deploy: service`，工具仍只有内置 `http_request` 和受限的 Pi `read`。无需 Shell、活动 API、额外进程或新 Tool。Skill 附带 JSON 已在资源读取范围内；活动查询可以不联网，但模型服务仍需可用。

按 [示例说明](../README.md) 填写当前 Bot 的 endpoints.yml 后，在仓库根目录运行：

```bash
cota shell --config bots/weather --debug
```

通过 `cota init` 创建的副本使用 `--config cota_projects/weather`。init 不覆盖已有副本；测试本次修改请直接使用 bots/weather 或自行同步 Skill、Policy、agent.yml，保留自己的 endpoints.yml 和数据。

weather 使用 Open-Meteo 的 current 与 daily 数据，支持当前天气和从当地今天起最长16天的逐日预报，包括明天和周末；超出范围、接口失败或数据缺失时如实说明本次无法确认。不能用实况代替未来预报。API 参数与天气代码见 [Open-Meteo 文档](https://open-meteo.com/en/docs)。公开接口的使用范围、配额及商业部署要求以供应商条款为准。

开发者说明：activities.json 仍是固定的虚构活动测试集，不是真实营业信息。本示例用正常业务名称、价格与状态检验模型的业务选择能力；测试说明仅保留在开发文档，不作为 Skill、工具结果或回答的测试标签。正式给游客使用前应接入真实数据。available 不包含指定日期的营业、余票或预订信息。

## 手动验证

Bot 定位、Skill description 和 Policy 使用正常业务表述；基础 prompt 不指定任务与 Skill 名称的一一映射，让模型依据能力描述和 Policy 选择。Bot 回复以用户需求为中心：先给推荐及关键理由，保留必要的事实与不确定性，不汇报工具选择、文件读取或筛选流程。用户输入也应使用自然业务需求，不刻意提示“模拟”或 Skill 名称。

每组独立案例使用新会话；表中标为“接着说”的内容在同一会话中测试。不要固定要求唯一的 Skill 阅读顺序，已读指引也不必重复读取。

| 输入/操作 | 应核验的行为 |
| --- | --- |
| 你好 | 介绍能力，无需查询天气或活动 |
| 帮我查下天气 → 北京 | 补齐城市后查询，只报告实际天气，不进入活动规划 |
| 上海和杭州现在的天气怎么样 | 分别查询，城市、来源、时间对应正确 |
| 杭州有哪些亲子活动？先不用查天气 | 读取 activity-search 和 JSON；不需要 HTTP |
| 杭州，两大一小，室内亲子活动，门票总预算三百 | 科技馆 hz-science 为 60×3=180 元；手作坊 150×3=450 元不合预算；满额条目不能推荐 |
| 接着说：预算改成一百，仍然只要室内 | 明确无匹配，询问是否放宽条件；不能偷偷改成户外或推荐满额条目 |
| 接着说：改回三百，换上海，人数不变 | 上海 sh-aquarium 为 90×3=270 元；不沿用杭州候选与价格；价格未知展览不能算免费 |
| 杭州今天带孩子出门，两大一小，门票三百以内，帮我做方案 | 组合三个 Skill；按目标天气和实际活动字段给建议，费用范围为门票，不输出内部流程 |
| 如果下雨就去室内 | 假设不等于实际下雨；结合已有天气证据或明确未知 |
| 周末杭州带孩子玩，如果下雨就去室内，三个人门票三百以内 | 查询对应周末日期的预报，结合活动给方案；失败时给条件建议，不承诺营业和余票 |
| 帮我找成都的亲子活动 | 简短说明暂未查到成都活动，不编造活动，不说现实中没有活动 |
| 接着说：算了，只告诉我北京现在的天气 | 停止活动规划，按新任务查询北京 |
| 天气服务不可用，但目录可读 | 如实说明天气未知，可以提供有数据依据的候选，不把失败解释成下雨 |
| 追问后重启并恢复同一 session_id | 保留对话和资源读取证据；shell 重启默认新会话，跨重启测试请用固定 session_id 的 API 客户端 |

总预算与每人预算要明确区分；成人儿童在模拟目录中同价。门票合计不包含餐饮、交通。回复无需显示条目 ID 或测试标签，不能声称已经预约。

## Debug 与自动化验证

在 Skills & Tools 查看三个 Skill 的发现情况；在 Events 查看 read 调用与 tool_result：

- SKILL.md 阅读记录为 resource.kind=skill。
- activities.json 阅读记录为 resource.kind=reference，归属 activity-search，并保留文件哈希。
- JSON 不是另一个 Skill，也不意味着某个业务步骤已经完成。
- 在 Model Requests 检查真实读取的数据是否进入后续请求，以及 business_guidance 是否包含相关 Policy。

默认 all 策略提供最多 16 个案例，当前包含 12 个，留出少量补充标注的空间，适合先观察完整规则；使用检索策略时再比较案例命中与预算。案例中的结果条件必须由真实执行证据支持，不能直接当作已经发生的结果。

```bash
python -m pytest tests/test_bot_templates.py tests/integration/test_example_bots.py -q
```

自动化测试验证真实 Pi 多 Skill / JSON 读取、Policy 注入、SQLite 持久化恢复及 init/打包包含附带数据。模型响应与天气结果在测试中受控：这是执行合同测试，不代表真实模型已经通过上面的业务决策测试。真实 HTTP 的传输、地址限制和超时另有工具测试覆盖。

历史保存在本 Bot 的 workspace/sessions.db。HTTP 权限不是域名白名单；本次没有放宽资源或网络访问范围。

### 标注业务流程

已有会话可以导出为可填写的对话文件：

```bash
cota annotate export --config bots/weather --session SESSION_ID --output weather-review.yml
# 编辑 policies/name/steps；Bot 内按顺序填写 thought、skills、result 和 reply
cota annotate import --config bots/weather --input weather-review.yml --output weather-reviewed.yml
```

确认后将生成文件放入本 Bot 的 `policy/`，重新加载 Agent。也可以从零编写同格式 Policy。导出的 .source.json 来源文件无需编辑；标注人员不需要填写消息范围或事件 ID。详细说明见 [Skill 与对话标注](../../docs/src/concepts/skill-policy.md)。

### 训练和选择业务指导

默认使用 all 策略，无需训练。要尝试本地词项检索，将 agent.yml 的 policy 配置改成：

```yaml
policy:
  type: bm25
  max_policies: 4
  max_chars: 12000
  options:
    top_k: 8
```

然后执行：

```bash
cota train --config bots/weather
cota train --config bots/weather --check
cota shell --config bots/weather
```

案例或 options 修改后重新 train 并加载。索引保存为 `models/policy.json`，可随 Bot 包分享；运行时会校验版本。BM25 只提供相关候选，不判定实际天气成功或失败。模型选择、Embedding 和受限 grep/read 方案见 [可训练的 Policy](../../docs/src/concepts/trainable-policy.md)。

## 对话验证与 LLM 评测

首次使用最新模板：

```bash
cota init
cd cota_projects/weather
# 编辑 endpoints.yml，填写 llms.default 的 key、apibase、model
# 可选配置 llms.evaluator；不配置则使用 default 进行评测
cota eval
# 需要固定输出目录及额外模型诊断时：
cota eval --output workspace/evaluations/baseline --debug
```

weather 默认 all Policy 无需先训练。若改为需要训练产物的 Policy 方法，先执行 `cota train`。init 会跳过已存在的 Bot，不会自动更新旧目录中的验证文件。

案例覆盖：天气城市澄清、歧义、多城市、改口、明天及周末预报；活动人数与预算变更、预算临界值、每人/总价、免费/未知价/不可用项目、亲子与时长约束、费用范围、预订边界、优惠猜测、任务切换与取消。天气结果以实际服务为准，不预设网络一定成功或失败。


`policy/eval/data.yml` 随 Bot 一起交付，包含30个案例、43轮业务输入、94条 `reply-review`，不参与 Policy 训练。配置本 Bot 的 endpoints.yml 后运行：

```bash
cota eval --config bots/weather --output /tmp/weather-evaluation-1
cota eval --config bots/weather --case 'data.yml::future_condition' --repeat 3
cota eval judge --run /tmp/weather-evaluation-1 --config bots/weather --output /tmp/weather-rejudged
cota eval compare /tmp/weather-evaluation-1 /tmp/weather-evaluation-2 --output /tmp/weather-comparison
```

命令评测指定 Bot 的实际定义，不只借用模型配置。每个案例使用临时目录和独立 SQLite；同一案例保留真实多轮历史。所有案例默认运行，天气案例会调用公开天气接口，不提供旧脚本的 network 筛选开关；可用 `--case` 选择活动案例。

评委优先使用 endpoints.yml 中的 llms.evaluator；未配置时使用 llms.default，无需额外指定参数。已配置模型有误时会报错，不静默回退。结果目录含 results.json、可直接阅读的 report.md，以及逐轮执行 Trace 和评委请求/响应；`--debug` 额外保留 Bot 模型请求诊断。每条要求由 LLM 判断符合/不符合/无法判断，运行与评委错误单独记录。默认显示案例/轮次、执行或评判阶段，长时间等待每15秒提示一次，结束显示汇总；无需 --debug。

退出码0要求所有项通过，1表示存在失败、不确定或不完整，2表示配置/入口错误。模型评判仍需复核关键证据，自动化链路测试通过不代表业务准确率。完整格式、隔离边界及对比规则见[对话评测](../../docs/src/development/evaluation.md)。

对比修改前后的 Bot（保持验证文件、评委和执行超时一致）：

```bash
cota eval --output workspace/evaluations/after --debug
cota eval compare workspace/evaluations/baseline workspace/evaluations/after --output workspace/evaluations/comparison
```

以上命令在 Bot 目录执行。目录名称可自定义，但必须是新的。自动化脚本读取 results.json 的 summary、suite、bot、engine、judge，以及 comparison.json 的 comparable、summary、cases。评测退出码1表示存在不符合/不确定/不完整，不等于命令没有运行；报告仍会保存。

## 更新已有副本与核对评测

`cota init` 不覆盖已有 weather。更新模板时，对照合并 agent.yml、skills/、policy/ 和 README，保留自己的 endpoints.yml、业务修改与运行数据；训练型 Policy 更新案例后需重新 train，再加载 Bot。新增预报和回复指引需要同步这些 Bot 文件，仅升级框架不会改变旧副本的行为。

普通评测和 debug 评测都会把工具的结构化 result 与实际文本 content 交给评委。HTTP 响应正文可能位于 content，核对温度、日期、价格时不能只看 result 中的状态码。评委缺证据、误解要求或理由与结论矛盾时，先检查对应的 execution.json / judge.json；修正评判逻辑后用 `cota eval judge` 重评已有 Trace。

业务改进应保持同一验证集和评委条件做对比。新增回复风格要求会改变案例摘要，旧、新评测不能直接当作同一基准比较。模板与测试通过不保证真实模型每次都遵守表达要求，仍需保留和复核多余推荐、错误价格等失败案例。

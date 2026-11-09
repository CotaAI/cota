# 可训练的 Policy

Policy 是 Cota 在每次 Pi 主模型请求前提供业务指导的可扩展组件。标注文件继续使用 `policies/name/steps` 和有序的 thought、skills、result、reply。运营不需要额外标注检索标签。

训练不等于微调大模型：`cota train` 可以构建词项索引、生成 embedding、编译规则或冻结供模型搜索的案例语料。Policy 输出案例引用和适用性判断；公共层负责校验、预算、渲染和 Trace，不允许模型直接生成任意 system prompt。

## 生命周期

```text
policy/*.yml + agent.yml 的 policy 配置
  → cota train --config BOT
  → models/policy.json
  → 加载 Bot 时校验数据/配置/实现版本
  → Pi.prepareRequest
  → 当前对话和真实工具结果 → Policy.guidance
  → 原始案例 + 参考状态 → business_guidance
```

```bash
cota train --config bots/weather
cota train --config bots/weather --check
```

默认 `all` 不要求预训练，保持小型 Bot 开箱即用；对它执行 train 会生成可检查的训练记录，但运行时直接加载当前案例。其他策略必须先训练。产物缺失、内容损坏、案例或策略 options 变化时，加载失败并提示重新 train。修改注入预算不需要重建索引。

训练先生成和校验新产物，再用原子替换发布。失败不覆盖原产物；训练期间案例变化则拒绝发布。重新训练后需重新加载 Agent，现有实例不会自动热更新。训练使用 JSON，不反序列化 pickle。产物包含训练所需案例/索引/向量，应与 Bot 的其它业务配置一样管理。

## 内置策略

| type | 类 | train 内容 | 运行时行为 |
| --- | --- | --- | --- |
| all | AllPolicy | 空状态，不要求预训练 | 已读 Skill 相关案例优先，预算内提供完整案例 |
| bm25 | BM25Policy | 中英文词项频次索引 | 根据当前对话和工具结果排序，返回候选 |
| embedding | EmbeddingPolicy | 命名 embedding 服务生成的向量 | 查询向量与训练向量做余弦排序 |
| model | ModelPolicy | 完整案例语料 | 模型直接选择案例、关注的 Bot 步骤、状态与证据 |
| retrieval_model | RetrievalModelPolicy | BM25 或 embedding 索引及语料 | 检索候选后由模型判断适用性 |
| search_model | SearchModelPolicy | 可搜索的完整案例语料 | 模型使用受限 grep/read，再提交选择 |
| rule | RulePolicy | 已校验和标准化的字面匹配规则 | 对指定上下文字段匹配，只返回候选 |

BM25 使用拉丁词与中文字符/二元组，无需额外模型下载。索引区分用户需求、Skill、result 和 thought，避免长回复示例支配检索。Embedding 使用同一份字段表示，查询时不重算案例向量。两种检索均不宣称业务分支已成立；分数不是准确概率。

## 配置示例

所有配置位于 `agent.yml` 的 `policy` 下。除公共字段外，策略参数全部放在 `options`；未知字段明确报错。

```yaml
policy:
  type: retrieval_model
  artifact: models/policy.json
  max_policies: 4
  max_chars: 8000
  context_chars: 16000
  timeout_seconds: 20
  options:
    llm: policy_judge
    retriever: bm25
    retriever_options:
      top_k: 12
    input_chars: 32000
    model_tokens: 1200
```

`llm` 引用 `endpoints.yml` 现有 `llms` 中的名称。它可以与 Bot 执行模型相同，也可以独立配置；选择请求不执行业务工具。

纯本地检索无需模型凭证：

```yaml
policy:
  type: bm25
  options:
    top_k: 8
```

Embedding：

```yaml
policy:
  type: embedding
  options:
    embedding: policy_vectors
    top_k: 8
    min_score: 0
```

在 `endpoints.yml` 中增加命名资源：

```yaml
embeddings:
  policy_vectors:
    type: openai
    apibase: "https://embedding.example/v1"
    key: "填写 embedding 服务密钥"
    model: "填写 embedding 模型名称"
```

内置服务适配器支持 OpenAI-compatible embeddings，可选正整数 `dimensions`。train 按批请求向量；运行时只请求查询向量。模型、服务地址或维度配置变化会使索引失效，凭证轮换不会。凭证不进入训练产物。实际质量及 min_score 阈值需要用业务数据评测；默认 0 只是配置起点。

`retrieval_model` 使用向量候选时，设置 `retriever: embedding`，并将上面的 embedding/top_k/min_score 参数放进 `retriever_options`。

模型搜索：

```yaml
policy:
  type: search_model
  options:
    llm: policy_judge
    max_rounds: 4
    input_chars: 32000
    model_tokens: 1200
```

仅暴露 `grep_policies(query)` 和 `read_policy(name)`，查询是字面字符串、非正则；它们在已训练的 Policy 语料中搜索，不执行操作系统 grep/shell，不读取其它文件，不调用业务工具。每轮最多四个工具调用，轮数最多十轮；只能选择已经完整读取的案例。搜索输出和输入总量都受限，达到限制时退回已读案例候选并记录原因。

训练期固化规则：

```yaml
policy:
  type: rule
  options:
    rules:
      - policy: weather-city
        field: latest_user
        any: [朝阳, 哪个城市]
```

field 可选 latest_user、conversation、tool_results；any 是字面短语列表，进行 Unicode 标准化和不区分大小写匹配。规则引用的案例必须存在。匹配只表示相关候选，不将文本词汇解释为查询成功或业务完成。复杂的业务前提需要 model 判断或由执行模型结合实际证据判断。

## 运行时上下文、判断与降级

上下文取自当前 Pi 保留的非 system 消息，包含最近用户表达、实际 Bot 文本/工具调用以及工具返回。排除注入的 Policy 和模型 thinking 块。可对应到 DST 的消息携带 event_id；工具证据通过 cotaResultEventId、工具名、调用 ID、内容一致性核验。历史压缩摘要不伪装成原始事件，已被压缩移除的工具结果不悄悄作为当前证据使用。

context_chars 限制观察数据大小，大结果会标记 truncated，并为最新用户消息预留空间，避免工具长输出挤掉当前请求。不自动提取全局业务阶段，也不因 active_skill 推断业务进度。用户最新表达有独立检索权重，近期上下文帮助理解简短回答。Skill 读取正文和工具调用路径提供给判断模型，但不作为词项/向量检索的业务查询文本，避免仅因读取文档而误召回同一 Skill 的其它分支。当前词项检索仍可能受历史主题干扰，复杂取消/切换场景应通过 model 策略和评测验证。

模型选择状态：candidate（相关候选）、conditional（条件待确认）、applicable（模型判断当前步骤适用）、not_applicable（本次不采用）。applicable 必须有可见证据引用和有效 Bot 步骤；引用合法不等于语义判断一定正确。公共渲染保留整条案例和结果条件，仅标记关注步骤，不自动截断 SOP 或强制执行分支。not_applicable 不进入指导正文。

无匹配允许空指导。模型格式错误、服务错误或超时时，公共层回退到预算内候选并记录诊断，不将降级结果标成 applicable；retrieval_model 的模型判断失败仅退回检索候选。取消信号不被转换成降级结果。模型输入超出预算会省略完整案例并记录，不截断条件。模型调用令牌数、搜索轮数、输入长度和整体选择超时分别受限。

成功选择使用最多 64 项的实例内 LRU 缓存，键包含完整观察内容、会话和能力信息。新用户表达、工具结果或压缩变化会重新选择；不同会话不能共用判断。重新加载实例会清空缓存。

## 自定义 Policy

```python
from cota.policy import Policy, Match, Selection

class CompanyPolicy(Policy):
    version = "company-v1"
    option_names = frozenset({"preferred_case"})

    @classmethod
    def validate_options(cls, options):
        super().validate_options(options)
        if not isinstance(options.get("preferred_case"), str):
            raise ValueError("preferred_case is required")

    async def train(self, services):
        name = self.options["preferred_case"]
        if name not in {p["name"] for p in self.policies}:
            raise ValueError("Unknown case")
        return {"preferred_case": name}

    async def select(self, context, services):
        name = self.state["preferred_case"]
        eligible = {p["name"] for p in self.eligible(context)}
        return Selection([Match(name)] if name in eligible else [])
```

训练返回 JSON 状态，公共加载器校验版本/摘要后调用 `load_state(state)`；需要额外状态校验时覆盖该方法并调用 super。模型、索引格式或依赖算法语义变更时升级 version。

安装自定义模块后，可以直接配置 `type: company_package.policy:CompanyPolicy`；这是开发者配置的 Python 扩展，不接受标注文件中的可执行代码。嵌入式应用也可调用 `register_policy("company", CompanyPolicy)` 后使用 `type: company`；CLI 独立进程需可导入的模块路径，不能依赖另一进程中的注册。

`services.llm(name)` 返回现有 Cota 模型，`await services.embed(name, texts)` 返回向量；也可在 Python 集成时提供自定义 `PolicyServices`。纯规则策略无需模型。

## 检查是否生效

`bot_utter.payload.llm.policy` / `tool_started.payload.llm.policy` 保留策略类/版本、目录与策略指纹、实际注入案例的名称和哈希、选择状态、关注步骤及证据 ID。Debug 独立记录 preparation 保存完整 decisions、diagnostics、cache_hit、duration_ms、thoughts 和 omitted_policies；最终请求包含实际注入的案例文本。

这证明选择与注入过程，不证明主模型遵循了指导。使用同一批业务问题对比 all、bm25、model 等策略的能力选择、异常处理、回复事实性、token 与延迟，尤其检查“接口失败被误当作没有订单”和“用户取消后继续旧流程”。自动测试使用可控模型/embedding 响应，不代表真实模型质量评测。

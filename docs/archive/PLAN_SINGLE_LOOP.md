> 历史设计草案，仅保留设计过程。当前架构以 [定位与架构](../src/concepts/raas_architecture.md) 和 [执行流程](../src/concepts/execution-flow.md) 为准；本文件不属于发布手册。

> 历史设计稿：本文中的旧 Runtime、暂停状态和事件结构已被替换。当前实现请参阅 [执行流程](src/concepts/execution-flow.md) 和 [DST](src/concepts/dst.md)。

# COTA 2.0 Single-Loop 重构计划

## 设计总览

消除两层 Agent Loop（AgentRuntime + SkillExecutor），改为单层循环。
消除 Action 概念，用 Event Stream + read_skill tool 替代。

```
旧架构：
  User → Processor → AgentRuntime(LLM₁) → CustomAction → SkillExecutor(LLM₂) → tools
                                                            ↑ 独立子循环

新架构：
  User → Processor → AgentRuntime(LLM) → tools (exec/read/write/read_skill/ask_user/...)
                                           ↑ 单循环，read_skill 返回 SOP 文本
```

核心改动：
- DST 最小粒度：Action → Event
- agent.yml 配置：actions → skills
- 执行引擎：AgentRuntime 直接使用 ToolRegistry 中的所有 tool
- Skill 入口：read_skill tool（和 exec 完全平级）
- 上下文压缩：按 skill 标签分组压缩

---

## Phase 0: DST Event 体系

### 0.1 Event 数据结构

**文件：`cota/dst.py`**

```python
@dataclass
class Event:
    """DST 最小记录单元。"""
    type: str           # "user" | "skill_activate" | "tool_call" | "skill_complete" | "bot"
    timestamp: float = field(default_factory=time.time)
    text: str = ""
    skill: str = None   # tool_call 隶属的 skill（由 runtime._active_skill 标注）
    tool: str = None
    result: str = None  # 存储时截断到 500 字符
    metadata: Dict = field(default_factory=dict)
```

Event 类型说明：
| type | 含义 | 产生时机 |
|------|------|---------|
| user | 用户消息 | Processor.handle_message |
| skill_activate | read_skill 被调用 | AgentRuntime._handle_tool_calls 检测到 _read_skill 标记 |
| tool_call | 通用 tool 执行 | AgentRuntime._handle_tool_calls |
| skill_complete | skill 执行结束 | read_skill 切换 / text response / ask_user |
| bot | bot 最终回复 | AgentRuntime._on_text_response |

### 0.2 DST 核心重写

**文件：`cota/dst.py`**

删除的字段：
- `self.actions: deque`
- `self.latest_action`
- `self.latest_sender_id` / `self.latest_receiver_id`
- `self.slots`

新增/保留的字段：
```python
class DST:
    def __init__(self, session_id, agent, user_id=None):
        self.session_id = session_id
        self.agent = agent
        self.user_id = user_id

        # Event stream
        self.events: List[Event] = []

        # 快捷引用
        self.latest_user_event: Optional[Event] = None
        self.latest_bot_event: Optional[Event] = None

        # 运行时状态（不持久化到 Store）
        self._live_messages: List[Dict] = []  # 当前 LLM 循环的 messages

        # 持久化状态
        self._user_context: Dict = {}
        self._session_vars: Dict = {}
        self.paused_state: Optional[Dict] = None  # ask_user 暂停时保存
```

核心方法：

```python
def append_event(self, event: Event):
    self.events.append(event)
    if event.type == "user":
        self.latest_user_event = event
    elif event.type == "bot":
        self.latest_bot_event = event

def latest_user_text(self) -> str:
    if self.latest_user_event:
        return self.latest_user_event.text
    return ""
```

### 0.3 DST Observe 方法重写

保留的 observe 方法（用新 events 实现）：
- `task_description` → `self.agent.description`
- `user_context_text` → 不变
- `session_summary` → 用 events 重新实现

新增：
- `skill_descriptions(action=None)` → 列出所有 skill 名称 + 描述
- `compressed_history(action=None)` → 按 skill 压缩的历史文本

删除：
- 所有 `latest_action_*` 方法
- `action_names` / `action_descriptions`
- `history_actions` / `history_actions_with_thoughts`
- `history_messages`（用 compressed_history 替代）

### 0.4 DST 序列化

```python
def as_dict(self) -> Dict:
    """序列化时按 skill 压缩 tool_call events。"""
    compressed_events = self._compress_events_for_storage()
    return {
        "session_id": self.session_id,
        "user_id": self.user_id,
        "events": compressed_events,
        "user_context": self._user_context,
        "session_vars": self._session_vars,
        "paused_state": self.paused_state,
    }
```

压缩规则：连续的同 skill tool_call 合并为 skill_run：
```python
def _compress_events_for_storage(self):
    compressed = []
    pending_skill = None
    pending_tools = []

    for e in self.events:
        if e.type == "tool_call":
            if e.skill != pending_skill and pending_tools:
                compressed.append(self._make_skill_run(pending_skill, pending_tools))
                pending_tools = []
            pending_skill = e.skill
            pending_tools.append(e)
        else:
            if pending_tools:
                compressed.append(self._make_skill_run(pending_skill, pending_tools))
                pending_skill, pending_tools = None, []
            compressed.append(e.as_dict())

    if pending_tools:
        compressed.append(self._make_skill_run(pending_skill, pending_tools))
    return compressed

def _make_skill_run(self, skill, events):
    return {
        "type": "skill_run", "skill": skill,
        "tool_count": len(events),
        "tools": [e.tool for e in events],
        "result": events[-1].result[:200] if events[-1].result else "",
        "ts": events[0].timestamp,
    }
```

反序列化：`skill_run` 还原为一个 `skill_complete` event（不展开）。

### 0.5 Store 适配

**文件：`cota/store.py`**

完全重写。不再按 action 逐条存储，改为按 session 存储整个 DST 快照。

```python
class MemoryStore(Store):
    def __init__(self):
        self.store: Dict[str, Dict] = {}  # session_id → dst_dict

    async def save(self, dst: DST) -> None:
        self.store[dst.session_id] = dst.as_dict()

    async def retrieve(self, session_id: str) -> Optional[Dict]:
        return self.store.get(session_id)
```

SQLStore 同理：改为 sessions 表，每行存一个 session 的 JSON。

```python
class SQLEvent(Base):
    __tablename__ = "sessions"
    session_id = sa.Column(sa.String(255), primary_key=True)
    user_id = sa.Column(sa.String(255), index=True)
    data = sa.Column(sa.Text)  # JSON: DST.as_dict()
    updated_at = sa.Column(sa.Float)
```

---

## Phase 1: ReadSkillTool

### 1.1 创建 ReadSkillTool

**文件：`cota/executor/tools/read_skill.py`（新建）**

```python
class ReadSkillTool(Tool):
    """和 exec/read_file 完全平级的系统 tool。
    调用后返回 SOP 文本，同时 AgentRuntime 检测标记设置 active_skill。
    """

    def __init__(self, skill_registry: "SkillRegistry"):
        self._skill_registry = skill_registry

    @property
    def name(self): return "read_skill"

    @property
    def description(self):
        return "激活一个技能并获取操作指引。在执行具体任务前调用此工具。"

    @property
    def builtin(self): return True

    @property
    def parameters(self):
        return create_tool_schema(
            properties={
                "skill": {
                    "type": "string",
                    "enum": self._skill_registry.list_skill_names(),
                    "description": "技能名称"
                },
                "instruction": {
                    "type": "string",
                    "description": "从用户请求中提取的任务指令"
                }
            },
            required=["skill"]
        )

    async def execute(self, **kwargs):
        skill_name = kwargs["skill"]
        instruction = kwargs.get("instruction", "")
        sop = self._skill_registry.get_sop(skill_name)
        description = self._skill_registry.get_description(skill_name)
        return {
            "_read_skill": True,
            "skill": skill_name,
            "instruction": instruction,
            "content": f"## {skill_name}\n{description}\n\n{sop}",
        }
```

### 1.2 SkillRegistry 重构

**文件：`cota/executor/skills/loader.py`（修改）**

SkillRegistry 在现有基础上新增方法：

```python
class SkillRegistry:
    def list_skill_names(self) -> List[str]:
        return list(self._skills.keys())

    def get_sop(self, name: str) -> str:
        skill = self.get(name)
        return skill.content if skill else ""

    def get_description(self, name: str) -> str:
        skill = self.get(name)
        return skill.description if skill else ""
```

Skill 信息来源（优先级）：
1. `skills/<name>/SKILL.md` — frontmatter + markdown body（和 openclaw 一致）
2. agent.yml 中 `skills.<name>.description` — 覆盖 SKILL.md 的 description

### 1.3 ToolRegistry 适配

**文件：`cota/executor/tools/registry.py`（修改）**

`load_all_tools()` 新增参数：

```python
def load_all_tools(self, user_memory=None, mcp_pool=None, skill_registry=None):
    # ... 现有 tool 加载 ...

    if skill_registry and skill_registry.list_skill_names():
        from .read_skill import ReadSkillTool
        all_tools.append(ReadSkillTool(skill_registry))
```

TOOL_GROUPS 新增：
```python
"group:skill": ["read_skill"],
```

### 1.4 更新 __init__.py

**文件：`cota/executor/tools/__init__.py`（修改）**

新增导出 `ReadSkillTool`。

---

## Phase 2: AgentRuntime 单循环改造

### 2.1 初始化改造

**文件：`cota/runtime/agent_runtime.py`**

```python
class AgentRuntime(Runtime):
    def __init__(self, agent, dst, session_id, ...):
        super().__init__(max_iterations=max_iterations)
        self.agent = agent
        self.dst = dst
        self.session_id = session_id
        self.prompt = prompt or DEFAULT_AGENT_LOOP_PROMPT
        self.llm = llm

        # 单循环新增
        self._active_skill: Optional[str] = None
        self._tool_registry: ToolRegistry = agent.get_tool_registry()

        # 保留
        self._channel_callback = None
        self._has_replied = False
        self._dbg = LoopDebugger(...)
```

### 2.2 _build_tools_schema() 重写

```python
def _get_tools_schema(self):
    """从 ToolRegistry 获取所有 tool 的 OpenAI schema。"""
    tools = self._tool_registry.get_allowed_tools()
    return [tool.to_openai_schema() for tool in tools]
```

不再遍历 agent.actions 生成 function schema。所有 tool（包括 read_skill）统一从 ToolRegistry 获取。

### 2.3 _handle_tool_calls() 重写

核心逻辑：

```python
async def _handle_tool_calls(self, tool_calls, messages):
    tool_messages = []

    for tc in tool_calls:
        tool_name = tc["function"]["name"]
        arguments = json.loads(tc["function"].get("arguments", "{}"))

        # 统一执行
        tool = self._tool_registry.get(tool_name)
        if not tool:
            result_content = json.dumps({"error": f"Unknown tool: {tool_name}"})
        else:
            raw_result = await ToolWrapper(tool)(arguments)
            result_content = self._process_tool_result(
                tool_name, arguments, raw_result, messages
            )

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "content": result_content,
        })

        # 检查是否需要停止循环
        if self._should_stop:
            return tool_messages, True

    return tool_messages, False
```

### 2.4 _process_tool_result() — 统一的标记检测

```python
def _process_tool_result(self, tool_name, arguments, result, messages):
    """检测 tool result 中的控制标记，执行副作用，返回给 LLM 的文本。"""

    if isinstance(result, dict):
        # read_skill 标记
        if result.get("_read_skill"):
            return self._on_read_skill(result, messages)

        # ask_user 标记
        if result.get("_ask_user"):
            return self._on_ask_user(result, messages)

        # reply_user 标记
        if result.get("_reply_user"):
            return self._on_reply_user(result)

        # screenshot 标记
        if result.get("_screenshot_path"):
            return self._on_screenshot(result, messages)

    # 普通 tool result
    content = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)

    # 记录到 DST
    self.dst.append_event(Event(
        type="tool_call",
        skill=self._active_skill,
        tool=tool_name,
        result=content[:500],
    ))

    return content
```

### 2.5 副作用处理方法

```python
def _on_read_skill(self, result, messages):
    skill_name = result["skill"]

    # 结束上一个 skill
    if self._active_skill:
        self.dst.append_event(Event(type="skill_complete", skill=self._active_skill))
        self._compress_completed_skill(messages)

    # 激活新 skill
    self._active_skill = skill_name
    self.dst.append_event(Event(type="skill_activate", skill=skill_name, text=result.get("instruction", "")))

    return result["content"]  # SOP 文本返回给 LLM

def _on_ask_user(self, result, messages):
    question = result.get("question", "")

    # 保存暂停状态
    self.dst.paused_state = {
        "active_skill": self._active_skill,
        "messages": messages,
        "pending_tool_call_id": self._current_tc_id,
        "question": question,
    }

    if self._active_skill:
        self.dst.append_event(Event(type="skill_complete", skill=self._active_skill, metadata={"reason": "ask_user"}))

    self._should_stop = True
    return f"已向用户提问：{question}"

def _on_reply_user(self, result):
    msg = result.get("message", {})
    if self._channel_callback:
        # 异步发送（fire-and-forget）
        asyncio.create_task(self._channel_callback(msg))
    return "消息已发送给用户"

def _on_screenshot(self, result, messages):
    # 从 SkillExecutor 迁移 vision 注入逻辑
    # 将截图 base64 注入 messages 作为 image_url
    # 返回文本描述
    ...
```

### 2.6 _on_text_response() 重写

```python
async def _on_text_response(self, content, messages):
    if self._active_skill:
        self.dst.append_event(Event(type="skill_complete", skill=self._active_skill))
        self._active_skill = None

    if content:
        self.dst.append_event(Event(type="bot", text=content))
        self._has_replied = True

    self._dbg.log_final_dst(self.dst)
    self._dbg.close()
```

### 2.7 run() 中的 pause/resume

```python
async def run(self):
    paused = self.dst.paused_state
    user_query = self.dst.latest_user_text()

    if paused and user_query:
        # 恢复循环
        self._active_skill = paused.get("active_skill")
        resume_messages = paused["messages"]
        resume_messages.append({
            "role": "tool",
            "tool_call_id": paused["pending_tool_call_id"],
            "content": user_query,
        })
        self.dst.paused_state = None
        await self.run_loop(initial_messages=resume_messages)
    else:
        await self.run_loop()
```

### 2.8 删除的方法

- `_execute_action()`
- `_resume_action()`
- `_record_action()`
- `_record_bot_utter()`
- `_record_paused_skill()` / `_close_paused_skill()` / `_break_paused_skill()`
- `_find_paused_skill()`
- `_handle_paused_skill()`
- `_build_tools_schema()`（旧版，遍历 agent.actions）
- `_get_dynamic_policies()` 中遍历 agent.actions 的部分

---

## Phase 3: 上下文压缩

### 3.1 Skill 切换压缩

**文件：`cota/runtime/agent_runtime.py`**

```python
def _compress_completed_skill(self, messages):
    """在 messages 中找到当前 skill 的 read_skill 调用，将其后的 tool calls 压缩为摘要。"""
    # 找到最近的 read_skill 调用位置
    skill_start = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("function", {}).get("name") == "read_skill":
                    skill_start = i
                    break
        if skill_start is not None:
            break

    if skill_start is None:
        return

    # 压缩 skill_start 到当前位置的所有 assistant+tool 对
    before = messages[:skill_start]
    skill_messages = messages[skill_start:]

    tool_names = []
    last_result = ""
    for msg in skill_messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                name = tc.get("function", {}).get("name", "")
                if name != "read_skill":
                    tool_names.append(name)
        elif msg.get("role") == "tool":
            last_result = msg.get("content", "")[:200]

    summary = f"[{self._active_skill}] {len(tool_names)}次工具调用 → {last_result}"
    messages[:] = before + [{"role": "assistant", "content": summary}]
```

### 3.2 Skill 内滑动窗口压缩

**文件：`cota/runtime/agent_runtime.py`**（在 `_before_iteration` 中）

```python
COMPRESS_THRESHOLD_CHARS = 320_000
KEEP_RECENT_MESSAGES = 10

async def _before_iteration(self, iteration, messages):
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    if total_chars > self.COMPRESS_THRESHOLD_CHARS:
        self._sliding_window_compress(messages)
    return messages

def _sliding_window_compress(self, messages):
    """保留 system + user + read_skill 入口 + 最近 N 条，压缩中间部分。"""
    # 找到 read_skill 入口位置
    skill_header_end = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool" and i > 0:
            prev = messages[i-1]
            if prev.get("role") == "assistant" and prev.get("tool_calls"):
                for tc in prev["tool_calls"]:
                    if tc.get("function", {}).get("name") == "read_skill":
                        skill_header_end = i + 1
                        break

    # 分三段
    header = messages[:max(skill_header_end, 2)]  # system + user + read_skill 入口
    tail = messages[-self.KEEP_RECENT_MESSAGES:]   # 最近 N 条
    middle = messages[len(header):len(messages)-self.KEEP_RECENT_MESSAGES]

    if not middle:
        return

    # 压缩 middle
    tool_count = sum(1 for m in middle if m.get("role") == "assistant" and m.get("tool_calls"))
    summary = f"[{self._active_skill} 中间进度] {tool_count}次工具调用已执行"
    messages[:] = header + [{"role": "assistant", "content": summary}] + tail
```

### 3.3 跨轮历史压缩

**文件：`cota/dst.py`**

```python
def compressed_history(self, action=None) -> str:
    """Observe 方法：按 skill 压缩的历史文本，用于 system prompt。"""
    lines = []
    pending_skill = None
    pending_count = 0
    pending_result = ""

    for e in self.events:
        if e.type == "user":
            self._flush(lines, pending_skill, pending_count, pending_result)
            pending_skill, pending_count = None, 0
            lines.append(f"user: {e.text}")

        elif e.type == "skill_activate":
            self._flush(lines, pending_skill, pending_count, pending_result)
            pending_skill = e.skill
            pending_count, pending_result = 0, ""

        elif e.type == "tool_call":
            pending_count += 1
            if e.result:
                pending_result = e.result

        elif e.type in ("skill_complete", "skill_run"):
            # skill_run 来自反序列化的压缩记录
            if e.type == "skill_run":
                count = e.metadata.get("tool_count", 0)
                result = e.metadata.get("result", "")
                lines.append(f"[{e.skill}] {count}次调用 → {result[:100]}")
            else:
                self._flush(lines, pending_skill, pending_count, pending_result)
            pending_skill, pending_count = None, 0

        elif e.type == "bot":
            self._flush(lines, pending_skill, pending_count, pending_result)
            pending_skill, pending_count = None, 0
            lines.append(f"bot: {e.text}")

    self._flush(lines, pending_skill, pending_count, pending_result)
    return "\n".join(lines)

def _flush(self, lines, skill, count, result):
    if skill and count > 0:
        lines.append(f"[{skill}] {count}次调用 → {result[:100]}")
```

---

## Phase 4: Processor / Agent / Prompt

### 4.1 Processor 重写

**文件：`cota/processor.py`**

```python
class Processor:
    async def handle_message(self, message, channel=None):
        self.dst = await self.get_tracker(message.session_id, user_id=message.sender_id)

        # 记录用户消息（Event，不再是 UserUtter Action）
        self.dst.append_event(Event(type="user", text=message.text))

        if message.receiver != 'bot':
            await self.save_tracker(self.dst)
            return

        await self._handle_bot_turn(message.session_id, channel)
        await self.save_tracker(self.dst)

    async def _handle_bot_turn(self, session_id, channel=None):
        runtime = AgentRuntime(
            agent=self.agent,
            dst=self.dst,
            session_id=session_id,
            prompt=self.agent.dialogue.get("prompt"),
            llm=self.agent.dialogue.get("llm"),
            max_iterations=self.agent.dialogue.get("max_iterations", 30),
        )
        if channel:
            async def cb(msg):
                await channel.send_response(session_id, msg)
            runtime.set_channel_callback(cb)

        await runtime.run()

        # 发送最终回复到 channel
        if channel and self.dst.latest_bot_event:
            text = self.dst.latest_bot_event.text
            if text and not runtime._has_replied:
                # reply_user 已经发过的不重复发
                pass
            elif text:
                await channel.send_response(session_id, {
                    "sender": "bot", "sender_id": "default_bot",
                    "text": text, "metadata": {},
                })

        # 发送 ask_user 问题到 channel
        if channel and self.dst.paused_state:
            question = self.dst.paused_state.get("question", "")
            if question:
                await channel.send_response(session_id, {
                    "sender": "bot", "sender_id": "default_bot",
                    "text": question, "metadata": {"source": "ask_user"},
                })

    async def get_tracker(self, session_id, user_id=None):
        dst_dict = await self.store.retrieve(session_id)
        if dst_dict is None:
            tracker = DST(session_id=session_id, agent=self.agent, user_id=user_id)
        else:
            tracker = DST.from_dict(dst_dict, agent=self.agent)
            if user_id:
                tracker.user_id = user_id

        if tracker.user_id and self.agent.user_memory:
            tracker.load_user_context(self.agent.user_memory)
        return tracker

    async def save_tracker(self, tracker):
        await self.store.save(tracker)
```

### 4.2 Agent 重构

**文件：`cota/agent.py`**

关键改动：

```python
class Agent:
    def __init__(self, ...):
        # ... 保留 name, description, llms, dpl, store, dialogue ...
        self.skills: Dict = {}           # 替代 self.actions
        self._tool_registry: ToolRegistry = None
        self._skill_registry: SkillRegistry = None
        self.user_memory = None
        self.processor = Processor(agent=self, store=self.store)

    @classmethod
    def load_from_path(cls, path, store=None):
        agent_config = read_yaml_from_path(os.path.join(path, 'agent.yml'))
        endpoints_config = read_yaml_from_path(os.path.join(path, 'endpoints.yml'))

        # skills 配置（从 agent.yml 的 skills 字段读取）
        skills = agent_config.get("skills", {})

        # 加载 skill 定义（SKILL.md）
        skill_registry = load_skills(bot_path=path)

        # 用 agent.yml 的 skills 配置覆盖/补充 SKILL.md 信息
        for skill_name, skill_config in skills.items():
            if not skill_registry.get(skill_name):
                # agent.yml 中定义但没有 SKILL.md 的 skill
                # 用 description 作为 SOP
                skill_registry.register_inline(
                    name=skill_name,
                    description=skill_config.get("description", ""),
                    content=skill_config.get("sop", skill_config.get("description", "")),
                )

        # 初始化 ToolRegistry
        tool_registry = ToolRegistry()
        tool_registry.load_all_tools(
            user_memory=user_memory,
            mcp_pool=mcp_pool,
            skill_registry=skill_registry,
        )

        # 应用 service_mode 限制
        if service_mode:
            tool_registry.set_policy(ToolPolicy(deny=SERVICE_MODE_DENY))

        agent = cls(...)
        agent.skills = skills
        agent._skill_registry = skill_registry
        agent._tool_registry = tool_registry
        return agent

    def get_tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    def get_skill_registry(self) -> SkillRegistry:
        return self._skill_registry
```

### 4.3 agent.yml 新格式

```yaml
system:
  name: weather_bot
  description: 智能天气助手

dialogue:
  llm: deepseek
  max_iterations: 30
  max_tokens: 2000
  prompt: |
    你是一个智能天气助手。
    **可用技能：**
    {{skill_descriptions}}
    **对话历史：**
    {{compressed_history}}
    请根据用户需求，调用 read_skill 激活技能获取操作指引，然后使用工具完成任务。

skills:
  WeatherQuery:
    description: 查询单个城市的天气信息
```

### 4.4 Prompt 模板

**文件：`cota/constant.py`**

```python
DEFAULT_AGENT_LOOP_PROMPT = """你是一个智能助手。

**任务描述：**
{{task_description}}

**可用技能：**
{{skill_descriptions}}

**用户偏好：**
{{user_context_text}}

**决策参考：**
{{policies}}

**对话历史：**
{{compressed_history}}

请根据用户需求决定下一步：
- 需要执行任务时，先调用 read_skill 激活技能获取操作指引，再使用工具完成
- 简单问题直接文字回复
"""
```

---

## Phase 5: 删除废弃代码

### 删除的文件

```
cota/actions/action.py
cota/actions/custom_action.py
cota/actions/bot_utter.py
cota/actions/user_utter.py
cota/actions/rag.py
cota/actions/plugins/base.py
cota/actions/plugins/example.py
cota/actions/__init__.py
```

### 清理的引用

全局搜索并删除所有 `from cota.actions` 的 import。涉及：
- `cota/processor.py`
- `cota/runtime/agent_runtime.py`
- `cota/dst.py`
- `cota/agent.py`
- `cota/server.py`
- `tests/` 下所有文件

### DPL 适配

**文件：`cota/dpl/dpl.py`**

`generate_thoughts(dst, action)` 签名中的 `action` 参数：
- 改为 `generate_thoughts(dst, skill_name: Optional[str] = None)`
- 内部用 skill_name 替代 action.name 做匹配

**文件：`cota/dpl/match.py`、`cota/dpl/trigger.py`**

所有引用 `action.name` 的地方改为 `skill_name` 参数。

---

## Phase 6: 测试

### 新建测试文件

| 文件 | 内容 |
|------|------|
| `tests/test_event.py` | Event 创建、as_dict、from_dict |
| `tests/test_dst_v2.py` | DST events 管理、append_event、compressed_history、序列化（_compress_events_for_storage）、反序列化、paused_state |
| `tests/executor/test_read_skill.py` | ReadSkillTool 初始化（enum 来源）、execute 返回标记、SOP 获取 |
| `tests/runtime/test_single_loop.py` | mock LLM + mock tools → 完整单循环：user → read_skill → exec → text response |
| `tests/runtime/test_active_skill.py` | active_skill 设置（_on_read_skill）、清除（_on_text_response）、切换（连续 read_skill） |
| `tests/runtime/test_context_compression.py` | skill 切换压缩（_compress_completed_skill）、滑动窗口（_sliding_window_compress）、跨轮（compressed_history） |
| `tests/runtime/test_pause_resume.py` | ask_user → paused_state 保存 → 恢复 → 注入用户回答 → 继续循环 |
| `tests/runtime/test_multi_skill.py` | 一轮中 read_skill A → tools → read_skill B → tools → response。验证 DST events 正确、压缩正确 |

### 修改现有测试

| 文件 | 改动 |
|------|------|
| `tests/conftest.py` | MockAgent 新增 `get_tool_registry()`、`get_skill_registry()`、`skills` 字段；删除 `build_action` |
| `tests/test_processor.py` | 用 Event 替代 Action 验证流程 |
| `tests/test_store.py` | 验证新的 session 级存储格式 |
| `tests/executor/test_tool_registry.py` | 新增 read_skill 注册和 group:skill 测试 |

### 删除测试

```
tests/actions/test_action.py
tests/actions/test_bot_utter.py
tests/actions/test_user_utter.py
tests/actions/test_response.py
```

---

## 文件改动汇总

| 文件 | 操作 | Phase |
|------|------|-------|
| `cota/dst.py` | **重写** | 0 |
| `cota/store.py` | **重写** | 0 |
| `cota/executor/tools/read_skill.py` | **新建** | 1 |
| `cota/executor/tools/registry.py` | 修改 | 1 |
| `cota/executor/tools/__init__.py` | 修改 | 1 |
| `cota/executor/skills/loader.py` | 修改（新增方法） | 1 |
| `cota/runtime/agent_runtime.py` | **重写** | 2 |
| `cota/runtime/base.py` | 保持不变 | - |
| `cota/processor.py` | **重写** | 4 |
| `cota/agent.py` | **重写** | 4 |
| `cota/constant.py` | 修改 | 4 |
| `cota/dpl/dpl.py` | 修改签名 | 5 |
| `cota/dpl/match.py` | 修改 | 5 |
| `cota/dpl/trigger.py` | 修改 | 5 |
| `cota/actions/` (整个目录) | **删除** | 5 |
| `cota/server.py` | 修改（清理 import） | 5 |
| `cota/commander.py` | 修改（适配） | 5 |
| 8 个新测试文件 | **新建** | 6 |
| 4 个旧测试文件 | **删除** | 6 |
| 4 个现有测试文件 | 修改 | 6 |

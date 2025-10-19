DEFAULT_SELECTOR_INSTRUCTION = """
你是一个智能体，善于做规划和预测任务，请严格遵循用户指令回答。
"""

DEFAULT_FORM_UPDATER_INSTRUCTION = """
你是一个智能体，善于总结和归纳，你善于维护对话状态，请严格遵循用户指令回答。
"""

DEFAULT_SYSTEM_DESCRIPTION = """
你是一个认真负责的个人助理，你热情友善懂礼貌，善于解决用户的各种问题。
"""

DEFAULT_SYSTEM = {'description': DEFAULT_SYSTEM_DESCRIPTION}

DEFAULT_USER_DESCRIPTION = """你是一位友善的用户，向个人助理询问。"""

DEFAULT_USER = {'description': DEFAULT_USER_DESCRIPTION}

DEFAULT_QUERY_DESCRIPTION = """用户向智能体提问"""

DEFAULT_QUERY_PROMPT = """
你是一个普通用户，正在与智能助手对话寻求帮助。请根据历史对话内容，以用户的身份和口吻提出下一个合理的问题或回应。

**角色设定：**
- 你是一个需要帮助的普通用户
- 你会像正常人一样自然地交流，包括问候、感谢等
- 你希望得到满意的回复来解决问题

**历史对话：**
{{history_messages}}

**任务要求：**
1. 根据对话历史，判断当前对话进展
2. 如果对话刚开始或需要继续，提出合理的问题或回应
3. 如果已经得到满意答案，可以表示感谢并结束对话
4. 保持用户的自然对话风格，不要过于正式

**输出格式（严格按照JSON格式）：**
```json
{
  "thought": "你的内心想法和推理过程，分析当前对话状态和下一步应该说什么",
  "text": "你作为用户要说的话，自然、口语化的表达",
  "state": "continue/stop - continue表示对话继续，stop表示对话可以结束"
}
```
"""

DEFAULT_QUERY_BREAKER_DESCRIPTION = """判断是否终止对话"""

DEFAULT_QUERY_BREAKER_PROMPT = """
根据对话内容，判断是否可以终止对话

对话内容:
{{history_messages}}

如果对话完整且可以结束, 输出标识符true。
如果对话还需要继续, 输出标识符false。

输出格式为: <标识符>
"""

DEFAULT_QUERY_BREAKER = {'description': DEFAULT_QUERY_BREAKER_DESCRIPTION, 'prompt': DEFAULT_QUERY_BREAKER_PROMPT}

DEFAULT_RESPONSE_DESCRIPTION = """回复用户"""

DEFAULT_RESPONSE_PROMPT = """
根据任务描述和历史对话，生成回答。

任务描述:
{{task_description}}

历史对话:
{{history_messages}}

请回答用户
"""

DEFAULT_SELECTOR_DESCRIPTION = """选择合适的Action"""

DEFAULT_SELECTOR_PROMPT = """
根据历史Action序列，结合Action的描述，从Action列表中，选择最合适的Action。

Action列表:
{{bot_action_names_for_selector}}

Action描述为:
{{bot_action_descriptions_for_selector}}

历史Action序列为:
{{history_actions_for_selector}}

输出格式为: <Action>

"""

DEFAULT_FORM_PROMPT = """
当前正在执行{{current_form_name}}， 其描述为{{current_form_description}}。根据对话内容及Action序列，结合当前slot的状态，填充或重置slot的值。

历史Action序列为:
{{history_actions_for_update}}

Action的描述为:
{{action_descriptions}}

当前slots为:
{{current_form_slot_states}}

slots的含义为:
{{current_form_slot_descriptions}}

填充或重置slot的值, 保持slots格式输出json字符串。
"""

DEFAULT_HTTP_CLIENT_CONFIG = {
    "timeout": 10,
    "max_retries": 3,
    "default_headers": {"Content-Type": "application/json"}
}

DEFAULT_FORM_CONFIG = {
    "type": "form",
    "description": "",
    "prompt": DEFAULT_FORM_PROMPT,
    "slots": {},
    "executer": {
        "url": "",
        "method": "get",
        "mock": False,
        "output": []
    }
}

DEFAULT_DIALOGUE_MODE = """agent"""
DEFAULT_DIALOGUE_USE_PROXY_USER = False
DEFAULT_DIALOGUE_MAX_PROXY_STEP = 20
DEFAULT_DIALOGUE_MAX_TOKENS = 500
DEFAULT_DIALOGUE = {
    'mode': DEFAULT_DIALOGUE_MODE, 
    'use_proxy_user': DEFAULT_DIALOGUE_USE_PROXY_USER,
    'max_proxy_step': DEFAULT_DIALOGUE_MAX_PROXY_STEP, 
    'max_tokens': DEFAULT_DIALOGUE_MAX_TOKENS
}

DEFAULT_CONFIG = {
    'system': DEFAULT_SYSTEM,
    'user_proxy': DEFAULT_USER,
    'actions':{
        'UserUtter': {
            'description': '用户输入 - 此Action代表用户的输入消息，仅用于记录对话历史，Selector不应选择此Action',
            'prompt': DEFAULT_QUERY_PROMPT
        },
        'BotUtter': {
            'description': DEFAULT_RESPONSE_DESCRIPTION,
            'prompt': DEFAULT_RESPONSE_PROMPT
        },
        'Selector': {
            'description': DEFAULT_SELECTOR_DESCRIPTION,
            'prompt': DEFAULT_SELECTOR_PROMPT
        }
    },
    'dialogue':DEFAULT_DIALOGUE
}
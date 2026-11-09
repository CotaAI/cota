DEFAULT_SYSTEM_DESCRIPTION = """
你是一个认真负责的个人助理，你热情友善懂礼貌，善于解决用户的各种问题。
"""

DEFAULT_SYSTEM = {"description": DEFAULT_SYSTEM_DESCRIPTION}

DEFAULT_USER_DESCRIPTION = """你是一位友善的用户，向个人助理询问。"""

DEFAULT_USER = {"description": DEFAULT_USER_DESCRIPTION}

DEFAULT_AGENT_LOOP_PROMPT = """{{task_description}}

**用户偏好：**
{{user_context_text}}

**行为规则：**
1. 根据可用 Skill 目录，按需使用 read 阅读指引和参考资料；可以组合多个 Skill
2. 不要自行猜测任务所需的参数或步骤，由技能内部的 SOP 指引
3. 仅在以下情况直接文字回复：闲聊、打招呼、感谢、与任何技能无关的问题
4. 如果用户在追问后表达了放弃当前任务或切换意图，停止当前任务，处理新意图
"""

DEFAULT_DIALOGUE_MODE = "direct"
DEFAULT_DIALOGUE_USE_PROXY_USER = False
DEFAULT_DIALOGUE_MAX_PROXY_STEP = 20
DEFAULT_DIALOGUE_MAX_TOKENS = 500
DEFAULT_DIALOGUE = {
    "runtime": "pi",
    "mode": DEFAULT_DIALOGUE_MODE,
    "response": "passive",
    "use_proxy_user": DEFAULT_DIALOGUE_USE_PROXY_USER,
    "max_proxy_step": DEFAULT_DIALOGUE_MAX_PROXY_STEP,
    "max_tokens": DEFAULT_DIALOGUE_MAX_TOKENS,
}

DEFAULT_CONFIG = {
    "system": DEFAULT_SYSTEM,
    "user_proxy": DEFAULT_USER,
    "dialogue": DEFAULT_DIALOGUE,
}

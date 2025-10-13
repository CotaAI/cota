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
在此任务中,你扮演一个用户,遇到了一些问题,你需要多次沟通,最终得到满意的回复

历史对话:
{{history_messages}}

请根据历史对话输出提问
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
当前正在执行{{current_form_name}}, 其描述为{{current_form_description}}, 将结果返给用户。

结果为:
{{current_form_execute_result}}
"""
DEFAULT_FORM_UPDATER_DESCRIPTION = """更新状态"""
DEFAULT_FORM_UPDATER_PROMPT = """
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
DEFAULT_FORM_UPDATER = {'description': DEFAULT_FORM_UPDATER_DESCRIPTION, 'prompt': DEFAULT_FORM_UPDATER_PROMPT}

DEFAULT_HTTP_CLIENT_CONFIG = {
    "timeout": 10,
    "max_retries": 3,
    "default_headers": {"Content-Type": "application/json"}
}

DEFAULT_FORM_CONFIG = {
    "type": "form",
    "description": "",
    "prompt": "",
    "slots": {},
    "executer": {
        "url": "",
        "method": "get",
        "mock": False,
        "output": []
    },
    "updater": {
        "prompt": "",
        "llm": None
    }
}

DEFAULT_DIALOGUE_MODE = """agent"""
DEFAULT_DIALOGUE_MAX_BOT_STEP = 20
DEFAULT_DIALOGUE_USE_PROXY_USER = False
DEFAULT_DIALOGUE_MAX_PROXY_USER_STEP = 20
DEFAULT_DIALOGUE_USE_PROXY_USER_BREAKER = False
DEFAULT_DIALOGUE_MAX_TOKENS = 500
DEFAULT_DIALOGUE = {
    'mode': DEFAULT_DIALOGUE_MODE, 
    'max_bot_step': DEFAULT_DIALOGUE_MAX_BOT_STEP, 
    'use_proxy_user': DEFAULT_DIALOGUE_USE_PROXY_USER,
    'max_proxy_user_step': DEFAULT_DIALOGUE_MAX_PROXY_USER_STEP, 
    'use_proxy_user_breaker': DEFAULT_DIALOGUE_USE_PROXY_USER_BREAKER,
    'max_tokens': DEFAULT_DIALOGUE_MAX_TOKENS
}

DEFAULT_CONFIG = {
    'system': DEFAULT_SYSTEM,
    'user_proxy': DEFAULT_USER,
    'actions':{
        'UserUtter': {
            'description': DEFAULT_QUERY_DESCRIPTION,
            'prompt': DEFAULT_QUERY_PROMPT,
            'breaker': DEFAULT_QUERY_BREAKER
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

RAG_PROMPT_TEMPLATE="""
从文档

'''
{{knowledge}}
'''
中找问题

'''
{{question}}
'''
的答案，找到答案就仅使用文档语句回答问题，找不到答案就用自身知识回答并且告诉用户该信息不是来自文档。
不要复述问题，直接开始回答。
"""

RAG_SUMMARY_PROMPT="""
你的任务是概括用户的提问，根据本轮用户的输入和历史对话，概括出当前语境下，用户的提问，输出一定为疑问句。

本轮用户的输入是: 
{{latest_user_query}}

历史对话: 
{{history_messages}}
"""
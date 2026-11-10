"""Validate the supported Bot contract before creating runtime resources."""
import re
from math import isfinite


PROMPT_VARIABLES = {
    'task_description', 'agent_description', 'user_context_text', 'session_summary',
    'latest_user_query', 'compressed_history', 'history_messages', 'knowledge',
}


def _object(value, allowed, path):
    if not isinstance(value, dict):
        raise ValueError(f'{path} must be an object')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f'Unsupported {path} keys: {sorted(unknown)}; use the Skill/Tool/Policy contract')


def _names(value, path):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f'{path} must be a list of nonempty names')


def validate_bot_config(config):
    _object(config, {'system', 'dialogue', 'tools', 'policy', 'knowledge', 'channels', 'user_proxy', 'environment', 'deploy'}, 'agent')
    from cota.executor.environment import DEFAULT_DEPLOY, ExecutionEnvironment, NATIVE_TOOLS
    ExecutionEnvironment.for_deployment(config.get('deploy', DEFAULT_DEPLOY), config.get('environment', {}), base_path='.')
    _object(config.get('system', {}), {'name', 'description'}, 'system')
    for key, value in config.get('system', {}).items():
        if not isinstance(value, str):
            raise ValueError(f'system.{key} must be text')
    dialogue = config.get('dialogue', {})
    _object(dialogue, {'runtime', 'llm', 'prompt', 'max_iterations', 'max_tokens', 'pi_node',
                      'run_timeout_seconds', 'compaction',
                      'mode', 'response', 'use_proxy_user', 'max_proxy_step', 'proxy_prompt'}, 'dialogue')
    for key in ('max_iterations', 'max_tokens', 'max_proxy_step'):
        if key in dialogue and (type(dialogue[key]) is not int or dialogue[key] < 1):
            raise ValueError(f'dialogue.{key} must be a positive integer')
    compaction = dialogue.get('compaction', {})
    _object(compaction, {'reserve_tokens', 'keep_recent_tokens'}, 'dialogue.compaction')
    for key, value in compaction.items():
        if type(value) is not int or value < 1:
            raise ValueError(f'dialogue.compaction.{key} must be a positive integer')
    if 'run_timeout_seconds' in dialogue:
        value = dialogue['run_timeout_seconds']
        if type(value) not in (int, float) or not isfinite(value) or value <= 0:
            raise ValueError('dialogue.run_timeout_seconds must be positive and finite')
    for key in ('llm', 'prompt', 'pi_node', 'proxy_prompt'):
        if key in dialogue and not isinstance(dialogue[key], str):
            raise ValueError(f'dialogue.{key} must be text')
    if dialogue.get('mode', 'direct') not in ('direct', 'group'):
        raise ValueError('dialogue.mode must be direct or group')
    if dialogue.get('response', 'passive') not in ('passive', 'proactive'):
        raise ValueError('dialogue.response must be passive or proactive')
    if 'use_proxy_user' in dialogue and type(dialogue['use_proxy_user']) is not bool:
        raise ValueError('dialogue.use_proxy_user must be boolean')
    variables = set(re.findall(r'\{\{(\w+)\}\}', dialogue.get('prompt', '')))
    if variables - PROMPT_VARIABLES:
        raise ValueError(f'Unsupported prompt variables: {sorted(variables - PROMPT_VARIABLES)}')
    tools = config.get('tools', {})
    _object(tools, {'allow', 'deny'}, 'tools')
    for key, value in tools.items():
        _names(value, f'tools.{key}')
        if set(value) & NATIVE_TOOLS:
            raise ValueError('Configure Pi native tools through environment, not tools.allow/deny')
    from cota.executor.tools.registry import ToolPolicy
    ToolPolicy(**tools)  # Reject unknown groups before opening runtime resources.
    policy = config.get('policy', {})
    from cota.policy import validate_policy_config
    validate_policy_config(policy)
    if not isinstance(config.get('channels', {}), dict):
        raise ValueError('channels must be an object')
    _object(config.get('user_proxy', {}), {'description'}, 'user_proxy')
    knowledge = config.get('knowledge', [])
    if not isinstance(knowledge, list):
        raise ValueError('knowledge must be a list')
    for item in knowledge:
        _object(item, {'type', 'llm', 'prompt', 'max_tokens', 'temperature'}, 'knowledge entry')
        if item.get('type') != 'llm' or not isinstance(item.get('llm'), str) or not item['llm']:
            raise ValueError('knowledge entry requires type=llm and an llm name')

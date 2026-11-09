"""Trusted connection settings are never conversational memory."""
from types import SimpleNamespace
import json

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.executor.user_memory import MemoryUserMemory
from cota.processor import Processor
from cota.store import MemoryStore


async def test_processor_filters_device_connection_settings_before_recording_context(mock_agent):
    memory = MemoryUserMemory()
    memory.set('alice', 'mcp_auth_token', 'TOKEN_SENTINEL')
    memory.set('alice', 'mcp_endpoint', 'http://device.private')
    memory.set('alice', 'city', 'Hangzhou')
    mock_agent.user_memory = memory
    processor = Processor(mock_agent, MemoryStore())
    processor.dst = DST('memory-boundary', mock_agent)
    await processor._load_user_context('alice')
    assert processor.dst.user_context == {'city': 'Hangzhou'}
    assert 'TOKEN_SENTINEL' not in json.dumps([e.as_dict() for e in processor.dst.events])
    assert 'device.private' not in processor.dst.user_context_text()
    assert memory.get('alice', 'mcp_auth_token') == 'TOKEN_SENTINEL'


def test_old_context_cannot_put_device_secrets_back_in_prompt():
    dst = DST('old-context', SimpleNamespace(description='bot'))
    dst.append_event(Event('user_context_updated', {'user_id': 'alice',
        'context': {'mcp_auth_token': 'TOKEN_SENTINEL', 'city': 'Hangzhou'}}))
    dst.append_event(UserUtterEvent('hello'))
    assert dst.user_context_text() == '- city: Hangzhou'

"""Identity and memory are one atomic, replayable user context fact."""
from unittest.mock import Mock, AsyncMock
import pytest
from cota.dst import DST
from cota.events import Event
from cota.processor import Processor
from cota.store import MemoryStore
from cota.message.message import Message


def test_user_update_is_atomic_detached_and_deduplicated():
    dst = DST('s', None)
    context = {'city': '北京', 'flag': False}
    dst.update_user('alice', context)
    context['city'] = '上海'
    assert len(dst.events) == 1
    assert dst.events[0].type == 'user_context_updated'
    assert dst.events[0].payload == {'user_id': 'alice', 'context': {'city': '北京', 'flag': False}}
    dst.update_user('alice', {'city': '北京', 'flag': False})
    assert len(dst.events) == 1
    dst.update_user('alice', {'city': '北京', 'flag': 0})
    assert len(dst.events) == 2
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()


def test_switch_user_clears_previous_memory_and_refresh_failure_is_safe():
    dst = DST('s', None)
    dst.update_user('alice', {'private_preference': 'a'})
    memory = Mock()
    memory.get_all.side_effect = OSError('offline')
    dst.load_user_context(memory)
    assert len(dst.events) == 1
    dst.load_user_context(memory, user_id='bob')
    assert dst.user_id == 'bob' and dst.user_context == {}
    assert len(dst.events) == 2
    dst.user_id = None
    assert dst.events[-1].payload == {'user_id': None, 'context': {}}
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()


@pytest.mark.parametrize('payload', [{'context': {}}, {'user_id': 'a'}, {'user_id': 1, 'context': {}}, {'user_id': 'a', 'context': None}])
def test_user_context_requires_complete_valid_pair(payload):
    with pytest.raises(ValueError):
        Event('user_context_updated', payload)


def test_old_identity_event_is_removed():
    with pytest.raises(ValueError, match='Unknown event type'):
        Event('user_identified', {'user_id': 'a'})


@pytest.mark.asyncio
async def test_processor_records_one_user_context_event_and_skips_unchanged(mock_agent):
    store = MemoryStore()
    mock_agent.user_memory = Mock()
    mock_agent.user_memory.aget_all = AsyncMock(return_value={'city': '北京'})
    processor = Processor(mock_agent, store)
    for text in ('hello', 'again'):
        await processor.handle_message(Message(session_id='s', sender_id='alice', text=text, receiver='bot'))
    events = await store.events('s')
    contexts = [e for e in events if e['type'] == 'user_context_updated']
    assert len(contexts) == 1
    assert contexts[0]['payload'] == {'user_id': 'alice', 'context': {'city': '北京'}}
    assert mock_agent.user_memory.aget_all.await_count == 2
    assert (await store.load('s')).user_context == {'city': '北京'}

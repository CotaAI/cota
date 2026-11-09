import copy

import pytest

from cota.events import Event, UserUtterEvent, BotUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.store import MemoryStore, SQLStore


@pytest.fixture(params=['memory', 'sqlite'])
def durable_store(request, tmp_path):
    store = (MemoryStore() if request.param == 'memory' else
             SQLStore(db=str(tmp_path / 'sessions.db')))
    yield store
    if hasattr(store, 'engine'):
        store.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('original,replacement', [(False, 0), (True, 1), (1, 1.0)])
async def test_persisted_fact_comparison_preserves_json_types(durable_store, mock_agent, original, replacement):
    from cota.events import ToolResultEvent
    dst = DST('typed', mock_agent)
    dst.append_event(ToolResultEvent('native', result=original, tool_call_id='c', run_id='r'))
    await durable_store.save(dst)
    altered = [e.as_dict() for e in dst.events]
    altered[0]['payload']['result'] = replacement
    dst = DST.from_events(dst.session_id, altered, mock_agent, revision=dst.revision)
    with pytest.raises(ValueError, match='persisted event'):
        await durable_store.save(dst)
    stored = await durable_store.export_session('typed')
    assert type(stored['events'][0]['payload']['result']) is type(original)


@pytest.mark.asyncio
async def test_snapshot_is_detached(durable_store, mock_agent):
    dst = DST('s', mock_agent)
    dst.update_user('alice', {'nested': {'x': [1]}})
    dst.append_event(UserUtterEvent('original', metadata={'nested': [1]}))
    await durable_store.save(dst)
    dst.get_user_pref('nested')['x'].append(2)
    snapshot = await durable_store.export_session('s')
    assert snapshot['user_context']['nested']['x'] == [1]
    next(e for e in snapshot['events'] if e['type'] == 'user_utter')['payload']['metadata']['nested'].append(2)
    assert (await durable_store.history('s'))[0]['payload']['metadata']['nested'] == [1]


@pytest.mark.asyncio
async def test_stale_writer_cannot_overwrite(durable_store, mock_agent):
    dst = DST('s', mock_agent)
    await durable_store.save(dst)
    stale = (await durable_store.load('s', agent=mock_agent))
    dst.append_event(UserUtterEvent('new'))
    await durable_store.save(dst)
    with pytest.raises(RuntimeError, match='revision'):
        await durable_store.save(stale)
    assert (await durable_store.export_session('s'))['events'][-1]['payload']['text'] == 'new'


@pytest.mark.asyncio
async def test_history_separates_visible_and_execution_events(durable_store, mock_agent):
    dst = DST('s', mock_agent, user_id='alice')
    dst.append_event(UserUtterEvent('hello'))
    dst.append_event(Event(type='tool_started', payload={'tool_call_id': 'c', 'tool': 'exec', 'arguments': {}}))
    dst.append_event(BotUtterEvent('answer'))
    await durable_store.save(dst)
    assert [e['type'] for e in await durable_store.history('s')] == ['user_utter', 'bot_utter']
    assert len(await durable_store.history('s', include_execution=True)) == 4
    assert len(await durable_store.export_conversations('alice')) == 1
    assert await durable_store.export_conversations('bob') == []


def test_execution_checkpoint_roundtrip_and_detachment(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hi'))
    dst.append_event(Event('run_started', {'engine': 'pi'}, run_id='question-run'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(BotUtterEvent('waiting for input', run_id='question-run', llm={
        'request_id': 'q', 'request_sequence': 1, 'model': 'default', 'stop_reason': 'stop'}))
    snapshot = dst.as_dict()
    restored = DST.from_events(snapshot['session_id'], snapshot['events'], agent=mock_agent, revision=snapshot['revision'])
    assert restored.execution == dst.execution
    assert restored.events[-1].type == 'bot_utter'
    assert restored.events[-1].payload['llm'] == dst.events[-1].payload['llm']
    assert restored.events[-1].event_id == dst.events[-1].event_id
    restored.context_messages.clear()
    assert snapshot['context_messages']


def test_snapshot_preserves_question_trace_and_execution_without_mutation(mock_agent):
    source = DST('s', mock_agent)
    source.append_event(Event('run_started', {}, run_id='weather-run'))
    source.append_event(skill_result('weather'))
    source.append_event(BotUtterEvent('city?'))
    source.append_event(Event('run_finished', {'status': 'completed'}))
    source.append_event(UserUtterEvent('weather?', timestamp=123.5, event_id='user-1'))
    snapshot = source.as_dict()
    original = copy.deepcopy(snapshot)
    dst = DST.from_events(snapshot['session_id'], snapshot['events'], agent=mock_agent, revision=snapshot['revision'])
    assert dst.as_dict() == original
    dst.latest_bot_event.payload['text'] = 'another question?'
    dst.context_messages.append({'role': 'user', 'content': 'Beijing'})
    assert snapshot == original


def test_new_run_after_interruption_preserves_history_and_read_marker(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(Event('run_started', {'engine': 'pi'}, run_id='r'))
    dst.append_event(skill_result('payments'))
    dst.append_event(Event('run_finished', {'status': 'interrupted'}))
    before = dst.as_dict()['events']
    dst.append_event(UserUtterEvent('continue'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='new'))
    assert dst.execution['status'] == 'running'
    assert dst.execution['pending_tools'] == {}
    assert dst.active_skill == 'payments'
    assert dst.as_dict()['events'][:len(before)] == before
    assert not hasattr(dst, 'reset_execution')
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()


def test_new_mysql_tables_can_hold_full_traces():
    import sqlalchemy as sa
    from sqlalchemy.dialects import mysql
    for table in (SQLStore.SQLEvent.__table__, SQLStore.SQLSnapshot.__table__):
        ddl = str(sa.schema.CreateTable(table).compile(dialect=mysql.dialect()))
        assert 'LONGTEXT' in ddl


@pytest.mark.asyncio
async def test_store_event_queries_and_trace(durable_store, mock_agent):
    dst = DST('query', mock_agent)
    user = UserUtterEvent('hello')
    dst.append_event(user)
    dst.append_event(Event('run_started', {'input_event_id': user.event_id}, run_id='r'))
    dst.append_event(BotUtterEvent('done', run_id='r'))
    await durable_store.save(dst)
    assert [e['sequence'] for e in await durable_store.events('query', run_id='r', after_sequence=1, limit=1)] == [2]
    assert [e['type'] for e in await durable_store.history('query')] == ['user_utter', 'bot_utter']
    assert (await durable_store.trace('query', 'r'))['outputs'][0]['payload']['text'] == 'done'
    assert await durable_store.events('missing') == []
    assert (await durable_store.trace('missing', 'r'))['status'] == 'unknown'
    for kwargs in ({'limit': 0}, {'limit': 1001}, {'after_sequence': -1}, {'limit': 1.5}, {'after_sequence': False}):
        with pytest.raises(ValueError):
            await durable_store.events('query', **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['edit', 'delete', 'reorder'])
async def test_store_rejects_rewriting_persisted_facts(durable_store, mock_agent, mutation):
    dst = DST('immutable', mock_agent)
    dst.append_event(UserUtterEvent('one'))
    dst.append_event(BotUtterEvent('two'))
    await durable_store.save(dst)
    altered = [e.as_dict() for e in dst.events]
    if mutation == 'edit':
        altered[0]['payload']['text'] = 'rewritten'
    elif mutation == 'delete':
        altered.clear()
    else:
        altered.reverse()
        for index, event in enumerate(altered, 1):
            event['sequence'] = index
    dst = DST.from_events(dst.session_id, altered, mock_agent, revision=dst.revision)
    with pytest.raises(ValueError, match='persisted'):
        await durable_store.save(dst)
    saved = await durable_store.export_session('immutable')
    assert [e['payload']['text'] for e in saved['events']] == ['one', 'two']
    assert dst.revision == 1

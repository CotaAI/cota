"""Delivery state is separate from facts and committed with each new reply."""
import pytest
import sqlalchemy as sa

from cota.dst import DST
from cota.events import BotUtterEvent, UserUtterEvent
from cota.store import MemoryStore, SQLStore


TARGET = {'channel': 'feishu', 'scope': 'bot-a', 'chat_id': 'chat-a'}


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'delivery.db'))
    yield value
    if hasattr(value, 'engine'):
        value.engine.dispose()


def reply(sid='s', text='hello'):
    dst = DST(sid, None)
    dst.append_event(UserUtterEvent('question'))
    dst.append_event(BotUtterEvent(text))
    return dst


async def test_new_replies_only_are_enqueued_once(store):
    dst = reply()
    original = dst.events[-1]
    await store.save(dst)
    await store.save(dst, delivery_target=TARGET)
    assert await store.delivery('s', original.event_id) is None
    dst.append_event(BotUtterEvent('second'))
    event = dst.events[-1]
    await store.save(dst, delivery_target=TARGET)
    await store.save(dst, delivery_target=TARGET)
    rows = await store.due_deliveries({'feishu': 'bot-a'}, 0)
    assert len(rows) == 1
    row = rows[0]
    assert row == await store.delivery('s', event.event_id)
    assert row['sequence'] == event.sequence
    assert row['status'] == 'pending' and row['attempts'] == 0
    assert row['next_attempt_at'] == 0 and row['error_type'] is None
    assert set(row) == {'id', 'session_id', 'event_id', 'sequence', 'channel', 'scope', 'chat_id',
                        'status', 'attempts', 'next_attempt_at', 'error_type'}
    assert await store.delivery('s', dst.events[0].event_id) is None


async def test_head_order_is_across_sessions_and_failed_head_blocks(store):
    first, second, other = reply('first'), reply('second'), reply('other')
    for dst in (first, second):
        await store.save(dst, delivery_target=TARGET)
    await store.save(other, delivery_target={**TARGET, 'chat_id': 'chat-b'})
    assert [r['session_id'] for r in await store.due_deliveries({'feishu': 'bot-a'}, 0)] == ['first', 'other']
    eid = first.events[-1].event_id
    attempt = await store.begin_delivery('first', eid)
    assert attempt['attempts'] == 1
    await store.finish_delivery('first', eid, error='TimeoutError', retry_at=10)
    assert [r['session_id'] for r in await store.due_deliveries({'feishu': 'bot-a'}, 9)] == ['other']
    assert [r['session_id'] for r in await store.due_deliveries({'feishu': 'bot-a'}, 10, limit=1)] == ['first']
    await store.begin_delivery('first', eid)
    await store.finish_delivery('first', eid, error='TimeoutError')
    assert (await store.delivery('first', eid))['status'] == 'failed'
    assert await store.begin_delivery('first', eid) is None
    assert [r['session_id'] for r in await store.due_deliveries({'feishu': 'bot-a'}, 100)] == ['other']
    assert await store.retry_delivery('first', eid)
    retried = await store.delivery('first', eid)
    assert retried['attempts'] == 0 and retried['next_attempt_at'] == 0 and retried['error_type'] is None
    assert not await store.retry_delivery('first', eid)
    await store.begin_delivery('first', eid)
    await store.finish_delivery('first', eid)
    assert not await store.retry_delivery('first', eid)
    assert await store.begin_delivery('first', eid) is None
    assert [r['session_id'] for r in await store.due_deliveries({'feishu': 'bot-a'}, 100)] == ['second', 'other']
    loaded = await store.load('first')
    assert loaded.as_dict() == first.as_dict()


async def test_scope_filter_and_detached_rows(store):
    first, second = reply('first'), reply('second')
    await store.save(first, delivery_target=TARGET)
    await store.save(second, delivery_target={**TARGET, 'scope': 'bot-b'})
    rows = await store.due_deliveries({'feishu': 'bot-b'}, 0)
    assert [r['session_id'] for r in rows] == ['second']
    rows[0]['status'] = 'delivered'
    assert (await store.delivery('second', second.events[-1].event_id))['status'] == 'pending'
    assert await store.due_deliveries({}, 100) == []
    assert await store.due_deliveries({'other-channel': 'bot-a'}, 100) == []
    assert await store.delivery('missing', 'missing') is None
    assert await store.begin_delivery('missing', 'missing') is None
    assert not await store.retry_delivery('missing', 'missing')


@pytest.mark.parametrize('target', [{}, {**TARGET, 'chat_id': ''}, {**TARGET, 'scope': 2},
                                    {**TARGET, 'channel': 'x' * 65}, {**TARGET, 'chat_id': 'x' * 256}])
async def test_invalid_target_cannot_commit_facts(store, target):
    dst = reply()
    with pytest.raises(ValueError):
        await store.save(dst, delivery_target=target)
    assert await store.load('s') is None
    assert dst.revision == 0


async def test_sql_insert_failure_rolls_back_reply_and_delivery(tmp_path):
    store = SQLStore(db=str(tmp_path / 'rollback.db'))
    dst = reply()
    await store.save(dst)
    dst.append_event(BotUtterEvent('new reply'))
    before = (await store.load('s')).as_dict()
    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO deliveries'):
            raise RuntimeError('injected insert failure')
    sa.event.listen(store.engine, 'before_cursor_execute', fail_insert)
    try:
        with pytest.raises(RuntimeError, match='injected'):
            await store.save(dst, delivery_target=TARGET)
        assert (await store.load('s')).as_dict() == before
        assert await store.delivery('s', dst.events[-1].event_id) is None
    finally:
        sa.event.remove(store.engine, 'before_cursor_execute', fail_insert)
        store.engine.dispose()


async def test_sql_reopen_recovers_pending_rows(tmp_path):
    path = str(tmp_path / 'recover.db')
    store = SQLStore(db=path)
    dst = reply()
    await store.save(dst, delivery_target=TARGET)
    eid = dst.events[-1].event_id
    await store.begin_delivery('s', eid)
    await store.finish_delivery('s', eid, error='OSError', retry_at=20)
    store.engine.dispose()
    reopened = SQLStore(db=path)
    try:
        assert await reopened.due_deliveries({'feishu': 'bot-a'}, 19) == []
        rows = await reopened.due_deliveries({'feishu': 'bot-a'}, 20)
        assert len(rows) == 1 and rows[0]['attempts'] == 1 and rows[0]['error_type'] == 'OSError'
        assert (await reopened.event_by_id('s', eid))['payload']['text'] == 'hello'
    finally:
        reopened.engine.dispose()


async def test_memory_preparation_failure_commits_neither_reply_nor_delivery(monkeypatch):
    store = MemoryStore()
    dst = reply()
    await store.save(dst)
    before = (await store.load('s')).as_dict()
    dst.append_event(BotUtterEvent('new reply'))
    def fail_rows(*args):
        raise RuntimeError('injected preparation failure')
    monkeypatch.setattr('cota.store.delivery_rows', fail_rows)
    with pytest.raises(RuntimeError, match='injected'):
        await store.save(dst, delivery_target=TARGET)
    assert (await store.load('s')).as_dict() == before
    assert await store.delivery('s', dst.events[-1].event_id) is None


async def test_sql_due_query_is_bounded_and_uses_target_indexes(tmp_path):
    store = SQLStore(db=str(tmp_path / 'bounded.db'))
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    sa.event.listen(store.engine, 'before_cursor_execute', capture)
    try:
        await store.due_deliveries({'feishu': 'bot-a'}, 10, limit=2)
        query = next(s for s in statements if s.startswith('SELECT'))
        assert 'LIMIT' in query and 'EXISTS' in query
        table = store.SQLDelivery.__table__
        index_columns = {tuple(c.name for c in i.columns) for i in table.indexes}
        assert ('channel', 'scope', 'chat_id', 'id', 'status') in index_columns
        assert ('channel', 'scope', 'status', 'next_attempt_at', 'id') in index_columns
        # Compile against MySQL and check utf8mb4 key widths without a server.
        from sqlalchemy.dialects import mysql
        from sqlalchemy.schema import CreateTable, CreateIndex
        assert 'AUTO_INCREMENT' in str(CreateTable(table).compile(dialect=mysql.dialect()))
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=mysql.dialect()))
            assert sum(getattr(c.type, 'length', None) * 4 if getattr(c.type, 'length', None)
                       else 8 for c in index.columns) <= 3072
    finally:
        sa.event.remove(store.engine, 'before_cursor_execute', capture)
        store.engine.dispose()

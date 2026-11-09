import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.application import Application
from cota.store import MemoryStore, SQLStore
from tests.test_group_conversation import group_app


def fast(app):
    app.group.debounce_seconds = .01
    app.group.max_wait_seconds = .03
    app.group.judgement_interval = .02


async def test_negative_decision_does_not_hide_new_need_for_a_minute(mock_agent):
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(side_effect=[False, True])
        a = await app.submit(user_id='a', session_id='g', text='闲聊', message_id='a')
        assert (await a.wait())['receipt']['status'] == 'recorded'
        b = await app.submit(user_id='b', session_id='g', text='有个问题需要帮忙', message_id='b')
        assert (await b.wait())['receipt']['status'] == 'completed'
        assert app.group.judge.decide.await_count == 2
        assert mock_agent._llm_mock.generate_chat.await_count == 1


@pytest.mark.parametrize('latest', ['不用了，取消这个问题', '我已经查到了，答案是晴天'])
async def test_answer_or_retraction_during_judgement_discards_old_yes(mock_agent, latest):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def judge(tracker):
        seen.append(tracker.latest_user_event.text)
        if len(seen) == 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                return True  # even a late provider result cannot authorize a stale run
            return True
        return False
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = judge
        first = await app.submit(user_id='a', session_id='g', text='天气呢', message_id='first')
        await asyncio.wait_for(entered.wait(), 2)
        second = await app.submit(user_id='b', session_id='g', text=latest, message_id='second')
        release.set()
        await asyncio.wait_for(asyncio.gather(first.wait(), second.wait()), 2)
        mock_agent._llm_mock.generate_chat.assert_not_awaited()
        assert seen[-1] == latest
        assert not any(e['type'] == 'run_started' for e in await app.store.history('g', include_execution=True))


async def test_mention_does_not_wait_for_slow_participation_judge(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def judge(_):
        entered.set()
        await release.wait()
        return True
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = judge
        ordinary = await app.submit(user_id='a', session_id='g', text='question')
        await asyncio.wait_for(entered.wait(), 2)
        mention = await app.submit(user_id='b', session_id='g', text='明确求助', mentioned=True)
        assert (await asyncio.wait_for(mention.wait(), 5))['receipt']['status'] == 'completed'
        assert (await ordinary.wait())['receipt']['status'] == 'recorded'
        assert not release.is_set()


async def test_burst_is_coalesced_and_has_bounded_wait(mock_agent):
    async with group_app(mock_agent, response='proactive') as app:
        app.group.debounce_seconds = .08
        app.group.max_wait_seconds = .04
        app.group.judgement_interval = 0
        entered = asyncio.Event()
        async def judge(_):
            entered.set()
            return False
        app.group.judge.decide = AsyncMock(side_effect=judge)
        pending = []
        for i in range(5):
            pending.append(await app.submit(user_id='a', session_id='g', text=f'part {i}'))
            await asyncio.sleep(.005)
        await asyncio.wait_for(entered.wait(), .08)
        await asyncio.gather(*(s.wait() for s in pending))
        assert app.group.judge.decide.await_count == 1
        assert app.group.judge.decide.call_args.args[0].latest_user_event.text == 'part 4'


@pytest.mark.parametrize('sql', [False, True])
async def test_speech_cooldown_survives_restart_and_mentions_bypass_it(mock_agent, tmp_path, sql):
    store = SQLStore(db=str(tmp_path/'group.db')) if sql else MemoryStore()
    async with group_app(mock_agent, store, response='proactive') as app:
        await (await app.submit(user_id='a', session_id='g', text='hello', mentioned=True)).wait()
    if sql:
        store.engine.dispose()
        store = SQLStore(db=str(tmp_path/'group.db'))
    async with group_app(mock_agent, store, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(return_value=True)
        await (await app.submit(user_id='a', session_id='g', text='thanks')).wait()
        app.group.judge.decide.assert_not_awaited()
        await (await app.submit(user_id='a', session_id='g', text='explicit next', mentioned=True)).wait()
        assert mock_agent._llm_mock.generate_chat.await_count == 2
    if sql:
        store.engine.dispose()


async def test_close_resolves_pending_without_run_or_background_tasks(mock_agent):
    app = group_app(mock_agent, response='proactive')
    await app.start()
    app.group.debounce_seconds = 10
    app.group.max_wait_seconds = 10
    pending = await app.submit(user_id='a', session_id='g', text='help')
    duplicate = await app.submit(user_id='a', session_id='g', text='help', message_id=pending.message_id)
    assert duplicate.future is pending.future
    await asyncio.wait_for(app.close(), 2)
    assert (await pending.wait())['receipt']['status'] == 'recorded'
    assert not app.group._slots
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


async def test_new_inputs_do_not_cancel_started_proactive_result(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(return_value=True)
        first = await app.submit(user_id='a', session_id='g', text='help')
        await asyncio.wait_for(entered.wait(), 3)
        try:
            second = await app.submit(user_id='b', session_id='g', text='one')
            third = await app.submit(user_id='c', session_id='g', text='two')
            await asyncio.sleep(.02)
            assert not first.future.done()
        finally:
            release.set()
        assert (await asyncio.wait_for(first.wait(), 3))['receipt']['status'] == 'completed'
        await asyncio.gather(second.wait(), third.wait())


@pytest.mark.parametrize('sql', [False, True])
async def test_new_input_at_first_checkpoint_atomically_rejects_stale_run(mock_agent, tmp_path, sql, monkeypatch):
    from cota.processor import Processor
    store = SQLStore(db=str(tmp_path/'race.db')) if sql else MemoryStore()
    original = Processor._create_runtime
    async with group_app(mock_agent, store, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(side_effect=[True, False])
        async def before_start(processor, *args, **kwargs):
            runtime = await original(processor, *args, **kwargs)
            await app.submit(user_id='b', session_id='g', text='already answered')
            return runtime
        monkeypatch.setattr(Processor, '_create_runtime', before_start)
        first = await app.submit(user_id='a', session_id='g', text='help')
        assert (await first.wait())['receipt']['status'] == 'recorded'
        mock_agent._llm_mock.generate_chat.assert_not_awaited()
        assert not any(e['type'] == 'run_started' for e in await store.history('g', include_execution=True))
    if sql:
        store.engine.dispose()


async def test_close_after_new_input_preserves_started_result(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    app = group_app(mock_agent, response='proactive')
    await app.start()
    fast(app)
    app.group.judge.decide = AsyncMock(return_value=True)
    first = await app.submit(user_id='a', session_id='g', text='help')
    await asyncio.wait_for(entered.wait(), 3)
    second = await app.submit(user_id='b', session_id='g', text='later')
    closing = asyncio.create_task(app.close())
    release.set()
    await asyncio.wait_for(closing, 3)
    assert (await asyncio.wait_for(first.wait(), .3))['receipt']['status'] == 'completed'
    assert (await second.wait())['receipt']['status'] == 'recorded'


async def test_completed_run_without_utterance_does_not_start_speech_cooldown(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = [{'content': ''}, {'content': 'answer'}]
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(return_value=True)
        first = await app.submit(user_id='a', session_id='g', text='first')
        await first.wait()
        assert not any(e['type'] == 'bot_utter' for e in await app.store.history('g', include_execution=True))
        second = await app.submit(user_id='b', session_id='g', text='second')
        assert (await second.wait())['receipt']['status'] == 'completed'
        assert app.group.judge.decide.await_count == 2


async def test_pending_group_considerations_are_bounded_and_never_reserve_runner_slots(mock_agent):
    mock_agent.dialogue.update(mode='group', response='proactive')
    mock_agent.cleanup = AsyncMock()
    async with Application(mock_agent, max_pending=1) as app:
        app.group.debounce_seconds = 10
        app.group.max_wait_seconds = 10
        first = await app.submit(user_id='a', session_id='one', text='one')
        second = await app.submit(user_id='a', session_id='two', text='two')
        assert len(app.group._slots) == 1 and app.runner._pending == 0
        assert (await second.wait())['receipt']['status'] == 'recorded'
        mention = await app.submit(user_id='a', session_id='two', text='explicit', mentioned=True)
        assert (await mention.wait())['receipt']['status'] == 'completed'
    assert (await first.wait())['receipt']['status'] == 'recorded'


async def test_judgement_interval_is_short_but_enforced(mock_agent):
    async with group_app(mock_agent, response='proactive') as app:
        app.group.debounce_seconds = 0
        app.group.judgement_interval = .06
        starts = []
        async def judge(_):
            starts.append(asyncio.get_running_loop().time())
            return False
        app.group.judge.decide = judge
        await (await app.submit(user_id='a', session_id='g', text='one')).wait()
        await asyncio.wait_for((await app.submit(user_id='a', session_id='g', text='two')).wait(), 1)
        assert len(starts) == 2 and starts[1] - starts[0] >= .05


async def test_new_message_restarts_quiet_window(mock_agent):
    async with group_app(mock_agent, response='proactive') as app:
        app.group.debounce_seconds = .06
        app.group.max_wait_seconds = .3
        app.group.judgement_interval = 0
        starts = []
        async def judge(_):
            starts.append(asyncio.get_running_loop().time())
            return False
        app.group.judge.decide = judge
        first = await app.submit(user_id='a', session_id='g', text='one')
        await asyncio.sleep(.02)
        second = await app.submit(user_id='a', session_id='g', text='two')
        received = asyncio.get_running_loop().time()
        await asyncio.wait_for(asyncio.gather(first.wait(), second.wait()), 1)
        assert len(starts) == 1 and starts[0] - received >= .05


async def test_superseded_queued_candidate_has_terminal_receipt_before_capacity_returns(mock_agent):
    from cota.channels.events import InboundMessage
    release = asyncio.Event()
    async with group_app(mock_agent, response='proactive') as app:
        app.runner.concurrency = 1
        fast(app)
        app.group.judge.decide = AsyncMock(return_value=True)
        blocker = await app.runner.submit(InboundMessage('application', 'a', 'busy', 'hold'), lambda _: release.wait())
        first = await app.submit(user_id='a', session_id='g', text='old', message_id='old')
        try:
            async with asyncio.timeout(2):
                while (await app.receipt('g', 'old'))['status'] != 'queued':
                    await asyncio.sleep(.005)
            second = await app.submit(user_id='b', session_id='g', text='new')
            assert (await asyncio.wait_for(first.wait(), .2))['receipt']['status'] == 'recorded'
        finally:
            release.set()
            await blocker
        await second.wait()


@pytest.mark.parametrize('closing', [False, True])
async def test_superseded_active_prestart_waits_for_runner_to_release_claim(mock_agent, monkeypatch, closing):
    entered, release = asyncio.Event(), asyncio.Event()
    async with group_app(mock_agent, response='proactive') as app:
        fast(app)
        app.group.judge.decide = AsyncMock(return_value=True)
        load = app.store.load
        async def gated(session, *args, **kwargs):
            if session == 'g' and asyncio.current_task() is app.runner._active.get('g') and not entered.is_set():
                entered.set()
                await release.wait()
            return await load(session, *args, **kwargs)
        monkeypatch.setattr(app.store, 'load', gated)
        first = await app.submit(user_id='a', session_id='g', text='old', message_id='old')
        await asyncio.wait_for(entered.wait(), 2)
        try:
            if closing:
                shutdown = asyncio.create_task(app.close())
                async with asyncio.timeout(2):
                    while not app.group._closed:
                        await asyncio.sleep(.005)
                await asyncio.sleep(.01)
            else:
                second = await app.submit(user_id='b', session_id='g', text='new')
            assert not first.future.done()
        finally:
            release.set()
        assert (await asyncio.wait_for(first.wait(), 2))['receipt']['status'] == 'recorded'
        if closing:
            await shutdown
        else:
            await second.wait()

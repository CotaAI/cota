"""User-visible behaviors migrated from the removed Python loop tests."""

import pytest
from cota.events.resources import skill_read_name

from cota.events import Event, UserUtterEvent, BotUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.mark.asyncio
@pytest.mark.parametrize('active,previous_question', [(False, False), (True, False), (True, True)])
async def test_business_guidance_applies_on_new_active_and_followup_turns(mock_agent, active, previous_question):
    dst = DST('s', mock_agent)
    if active:
        dst.append_event(Event('run_started', {}, run_id='prior-read'))
        dst.append_event(skill_result('SearchWeb'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
    if previous_question:
        dst.append_event(UserUtterEvent('previous question'))
        dst.append_event(BotUtterEvent('which city?'))
        dst.append_event(Event('run_started', {'engine': 'pi', 'input_event_id': dst.latest_user_event.event_id}, run_id='question-run'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('original question'))
    from cota.policy import PolicyCatalog, AllPolicy
    mock_agent.policy = AllPolicy(PolicyCatalog([{'name': 'reference', 'steps': [{'user': 'Applicable request'}, {'bot': [{'thought': 'business rule'}, {'skills': ['SearchWeb']}]}]}]))
    store = MemoryStore()
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert 'business rule' in messages[0]['content']
    assert 'Use the available tools to search the web.' not in messages[0]['content']
    assert '<active_skill' not in messages[0]['content']
    assert messages[-1]['content'] == 'original question'


@pytest.mark.asyncio
async def test_invalid_policy_skill_stops_before_model(mock_agent):
    from cota.policy import PolicyCatalog, AllPolicy
    mock_agent.policy = AllPolicy(PolicyCatalog([{'name': 'bad', 'steps': [{'bot': [{'thought': 'Invalid skill'}, {'skills': ['unknown']}]}]}]))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    with pytest.raises(ValueError, match='unknown'):
        await PiAgentRuntime(mock_agent, dst, 's').run()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_history_precedes_current_user_input(mock_agent):
    dst = DST('s', mock_agent)
    for event in (UserUtterEvent('old question'), BotUtterEvent('old answer'), UserUtterEvent('new question')):
        dst.append_event(event)
    await PiAgentRuntime(mock_agent, dst, 's').run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert [m['content'] for m in messages if m['role'] != 'system'] == [
        'old question', 'old answer', 'new question',
    ]


@pytest.mark.asyncio
async def test_reply_without_channel_is_saved_once(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(Event('run_started', {}, run_id='prior-read'))
    dst.append_event(skill_result('SearchWeb'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('reply'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'visible'},
    ]
    await PiAgentRuntime(mock_agent, dst, 's').run()
    assert [e.text for e in dst.events if e.type == 'bot_utter'] == ['visible']
    assert dst.active_skill == 'SearchWeb'
    assert len([e for e in dst.events if skill_read_name(e)]) == 1


@pytest.mark.asyncio
async def test_iteration_limit_keeps_checkpoint_and_fallback(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})]}
    store = MemoryStore()
    await PiAgentRuntime(mock_agent, dst, 's', max_iterations=1, checkpoint=store.save).run()
    assert dst.execution['status'] == 'limited'
    assert '最大步骤' in dst.latest_bot_text()
    assert (await store.export_session('s'))['execution']['status'] == 'limited'

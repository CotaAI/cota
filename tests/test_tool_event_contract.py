"""Compact facts must preserve Pi context and remain useful to Policy and Trace."""
from copy import deepcopy
import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent, ToolResultEvent
from cota.events.tool import result_content, text_result
from cota.snapshots import make_snapshot


@pytest.mark.parametrize('value', [None, False, 0, '', '123', [], {}, {'温度': 22}])
def test_default_result_is_stored_once_and_restores_native_value(value):
    event = ToolResultEvent('lookup', result=value, tool_call_id='c')
    assert set(event.payload) == {'tool_call_id', 'tool', 'status', 'result'}
    restored = Event.from_dict(event.as_dict())
    assert restored.result == value and type(restored.result) is type(value)
    assert result_content(restored.payload) == result_content(event.payload)


@pytest.mark.parametrize('status', ['success', 'error', 'blocked'])
@pytest.mark.parametrize('content', [None, [], [{'type': 'image', 'data': 'abc', 'mimeType': 'image/png'}]])
def test_compact_result_replay_snapshot_and_policy_join(status, content):
    dst = DST('compact', None)
    dst.append_event(UserUtterEvent('lookup order'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'lookup', 'arguments': {'order_id': '123'}}, run_id='r'))
    snapshot = make_snapshot(dst)
    event = ToolResultEvent('lookup', result={'found': True}, content=content, status=status, tool_call_id='c')
    dst.append_event(event)
    dst.append_event(BotUtterEvent('done'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    message = next(m for m in dst.context_messages if m['role'] == 'toolResult')
    assert message['content'] == result_content(event.payload)
    assert message['isError'] is (status != 'success')
    assert 'arguments' not in event.payload
    assert dst.trace('r')['calls'][0]['arguments'] == {'order_id': '123'}
    for cache in (None, snapshot, make_snapshot(dst)):
        assert DST.from_events(dst.session_id, dst.events, snapshot=cache).state_dict() == dst.state_dict()


def test_exact_content_override_is_detached_and_deduplicated():
    content = [{'type': 'text', 'text': 'hello'}]
    event = ToolResultEvent('read', result='hello', content=content)
    assert 'content' not in event.payload
    image = [{'type': 'image', 'data': 'abc', 'mimeType': 'image/png'}]
    event = ToolResultEvent('read', result=None, content=image)
    before = deepcopy(event.payload)
    image[0]['data'] = 'changed'
    result_content(event.payload)[0]['data'] = 'changed again'
    assert event.payload == before


@pytest.mark.parametrize('blocks,value', [
    ([{'type': 'text', 'text': ''}], ''),
    ([{'type': 'image', 'data': 'abc', 'mimeType': 'image/png'}], None),
    ([{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}], 'a\nb'),
])
def test_pi_result_preserves_empty_text_and_stores_images_once(blocks, value):
    event = ToolResultEvent('read', result=text_result(blocks), content=blocks)
    assert event.result == value
    assert result_content(event.payload) == blocks


@pytest.mark.parametrize('kind', ['user', 'bot'])
def test_old_utterance_types_are_not_accepted(kind):
    with pytest.raises(ValueError, match='Unknown event type'):
        Event(kind, {'text': 'old'})


class TestContextField:
    def test_valid_context_on_tool_result(self):
        event = ToolResultEvent('search_knowledge', result='text',
                                tool_call_id='c',
                                context={'mode': 'summary', 'summary': '[检索: "退款" → 2条]'})
        assert event.payload['context'] == {'mode': 'summary', 'summary': '[检索: "退款" → 2条]'}

    def test_context_not_required(self):
        event = ToolResultEvent('lookup', result='ok', tool_call_id='c')
        assert 'context' not in event.payload

    def test_invalid_context_mode_raises(self):
        with pytest.raises(ValueError, match='context'):
            ToolResultEvent('lookup', result='ok', tool_call_id='c',
                            context={'mode': 'invalid', 'summary': 'x'})

    def test_empty_summary_raises(self):
        with pytest.raises(ValueError, match='context'):
            ToolResultEvent('lookup', result='ok', tool_call_id='c',
                            context={'mode': 'summary', 'summary': ''})

    def test_context_projected_to_message(self):
        dst = DST('ctx', None)
        dst.append_event(UserUtterEvent('q'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
        dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'search_knowledge',
                                                 'arguments': {'query': '退款'}}, run_id='r'))
        dst.append_event(ToolResultEvent('search_knowledge', result='full text',
                                         tool_call_id='c',
                                         context={'mode': 'summary', 'summary': '[检索: "退款"]'}))
        msg = next(m for m in dst.context_messages if m['role'] == 'toolResult')
        assert msg['cotaContextSummary'] == '[检索: "退款"]'
        assert msg['content'][0]['text'] == 'full text'

    def test_no_context_means_no_summary(self):
        dst = DST('ctx2', None)
        dst.append_event(UserUtterEvent('q'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
        dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'bash',
                                                 'arguments': {'command': 'ls'}}, run_id='r'))
        dst.append_event(ToolResultEvent('bash', result='file.txt', tool_call_id='c'))
        msg = next(m for m in dst.context_messages if m['role'] == 'toolResult')
        assert 'cotaContextSummary' not in msg

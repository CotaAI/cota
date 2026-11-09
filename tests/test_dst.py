"""Tests for DST event persistence and business-message history."""

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent, ToolResultEvent
from tests.resource_fixtures import skill_result

class TestEvent:
    def test_event_creation(self):
        e = UserUtterEvent(text="hello")
        assert e.type == 'user_utter'
        assert e.text == "hello"
        assert e.skill is None
        assert e.timestamp > 0

    def test_event_as_dict(self):
        e = ToolResultEvent(tool='exec', result='ok')
        d = e.as_dict()
        assert d["type"] == "tool_result"
        assert d["payload"]["tool"] == "exec"
        assert d["payload"]["result"] == "ok"
        assert "timestamp" in d

    def test_event_from_dict(self):
        d = UserUtterEvent("hi", timestamp=1234567890).as_dict()
        e = Event.from_dict(d)
        assert isinstance(e, UserUtterEvent)
        assert e.type == 'user_utter'
        assert e.text == "hi"
        assert e.timestamp == 1234567890

    def test_event_result_not_truncated(self):
        long_result = "x" * 1000
        e = ToolResultEvent(tool='exec', result=long_result)
        d = e.as_dict()
        assert len(d["payload"]["result"]) == 1000

    def test_event_empty_fields_not_serialized(self):
        e = UserUtterEvent(text="hi")
        d = e.as_dict()
        assert "skill" not in d
        assert "tool" not in d
        assert "result" not in d
        assert "metadata" not in d



class TestDST:
    def test_append_event(self, dst):
        dst.append_event(UserUtterEvent(text="hello"))
        assert len(dst.events) == 1
        assert dst.latest_user_text() == "hello"

    def test_latest_user_and_bot(self, dst):
        dst.append_event(UserUtterEvent(text="q1"))
        dst.append_event(BotUtterEvent(text="a1"))
        assert dst.latest_user_text() == "q1"
        assert dst.latest_bot_text() == "a1"

    def test_question_uses_completed_run_lifecycle(self, dst):
        dst.append_event(Event('run_started', {}, run_id='ask'))
        dst.append_event(BotUtterEvent('what city?'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        assert dst.execution['status'] == 'completed'
        assert dst.latest_bot_text() == 'what city?'
        dst.append_event(UserUtterEvent('Beijing'))
        dst.append_event(Event('run_started', {}, run_id='answer'))
        assert dst.execution['status'] == 'running'
        assert DST.from_events(dst.session_id, dst.events).state_dict() == dst.state_dict()

    def test_active_skill_serialization_roundtrip(self, dst, mock_agent):
        dst.append_event(Event('run_started', {}, run_id='weather-run'))
        dst.append_event(skill_result('WeatherQuery'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        dst.append_event(UserUtterEvent(text="hello"))
        d = dst.as_dict()
        assert d["active_skill"] == "WeatherQuery"

        dst2 = DST.from_events(d['session_id'], d['events'], agent=mock_agent, revision=d['revision'])
        assert dst2.active_skill == "WeatherQuery"

    def test_active_skill_none_is_explicit(self, dst):
        d = dst.as_dict()
        assert d["active_skill"] is None

    def test_extract_messages(self, dst):
        dst.append_event(UserUtterEvent(text="hello"))
        dst.append_event(ToolResultEvent(tool='exec'))
        dst.append_event(BotUtterEvent(text="hi there"))

        msgs = dst.extract_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_observe_methods(self, dst):
        dst.append_event(UserUtterEvent(text="test query"))
        assert dst.observe("latest_user_query") == "test query"
        assert dst.observe("task_description") == "A test bot"

    def test_format_prompt(self, dst):
        dst.append_event(UserUtterEvent(text="hello"))
        prompt = "Task: {{task_description}}\nQuery: {{latest_user_query}}"
        result = dst.format_prompt(prompt)
        assert "A test bot" in result
        assert "hello" in result

    def test_observe_unknown_returns_empty(self, dst):
        result = dst.observe("policies")
        assert result == ""



class TestBuildHistoryMessages:
    def test_empty_events(self, dst):
        msgs = dst.build_history_messages()
        assert msgs == []

    def test_single_user_event_excluded_as_current_query(self, dst):
        """The last user event is the current query and should be excluded."""
        dst.append_event(UserUtterEvent(text="hello"))
        msgs = dst.build_history_messages()
        assert msgs == []

    def test_user_bot_expansion(self, dst):
        dst.append_event(UserUtterEvent(text="你好"))
        dst.append_event(BotUtterEvent(text="你好！有什么可以帮你的？"))
        dst.append_event(UserUtterEvent(text="查天气"))
        msgs = dst.build_history_messages()
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "你好"}
        assert msgs[1] == {"role": "assistant", "content": "你好！有什么可以帮你的？"}

    def test_last_user_event_excluded_from_middle(self, dst):
        """Only the very last user event is excluded, earlier ones are kept."""
        dst.append_event(UserUtterEvent(text="first"))
        dst.append_event(BotUtterEvent(text="reply1"))
        dst.append_event(UserUtterEvent(text="second"))
        dst.append_event(BotUtterEvent(text="reply2"))
        dst.append_event(UserUtterEvent(text="current"))
        msgs = dst.build_history_messages()
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert len(user_msgs) == 2
        assert user_msgs[0]["content"] == "first"
        assert user_msgs[1]["content"] == "second"



class TestSkillTrace:
    def test_active_skill_does_not_affect_prompt(self, dst):
        template = "{{session_summary}}\n{{compressed_history}}\n{{history_messages}}"
        dst.append_event(UserUtterEvent("hello"))
        original = dst.format_prompt(template)
        dst.append_event(Event('run_started', {}, run_id='weather-run'))
        dst.append_event(skill_result('weather'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        assert dst.format_prompt(template) == original
        dst.append_event(Event('run_started', {}, run_id='translation-run'))
        dst.append_event(skill_result('translation'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        assert dst.format_prompt(template) == original

    def test_skill_descriptions_is_not_a_prompt_variable(self, dst):
        assert dst.observe("skill_descriptions") == ""
        assert not hasattr(dst, "skill_descriptions")

    def test_read_and_tool_events_are_audit_only(self, dst):
        dst.append_event(UserUtterEvent("weather?"))
        dst.append_event(skill_result(skill="weather", text="Instructions"))
        dst.append_event(ToolResultEvent(tool='http_request', result='raw data'))
        dst.append_event(ToolResultEvent(tool='lookup', result='tool output'))
        dst.append_event(BotUtterEvent("sunny"))
        dst.append_event(Event(type="run_finished", payload={"status": "completed"}))
        dst.append_event(UserUtterEvent("thanks"))
        assert dst.build_history_messages() == [
            {"role": "user", "content": "weather?"},
            {"role": "assistant", "content": "sunny"},
        ]
        assert dst.compressed_history() == "user: weather?\nbot: sunny\nuser: thanks"
        assert len(dst.as_dict()["events"]) == 7

    def test_read_does_not_create_a_response(self, dst):
        dst.append_event(UserUtterEvent("weather?"))
        dst.append_event(skill_result(skill="weather"))
        dst.append_event(ToolResultEvent(tool='read', result='instructions'))
        dst.append_event(UserUtterEvent("translation?"))
        dst.append_event(skill_result(skill="translation"))
        assert dst.build_history_messages() == [{"role": "user", "content": "weather?"}]
        assert dst.compressed_history() == "user: weather?\nuser: translation?"

    def test_questions_and_answers_come_from_business_events(self, dst):
        dst.append_event(UserUtterEvent("weather?"))
        dst.append_event(skill_result(skill="weather"))
        dst.append_event(ToolResultEvent(tool='lookup', result='city?'))
        dst.append_event(BotUtterEvent("city?"))
        dst.append_event(UserUtterEvent("Beijing"))
        dst.append_event(ToolResultEvent(tool='http_request', result='raw weather'))
        dst.append_event(BotUtterEvent("Beijing is sunny"))
        dst.append_event(UserUtterEvent("another city?"))
        assert dst.build_history_messages() == [
            {"role": "user", "content": "weather?"},
            {"role": "assistant", "content": "city?"},
            {"role": "user", "content": "Beijing"},
            {"role": "assistant", "content": "Beijing is sunny"},
        ]


def test_resource_result_roundtrip():
    import cota
    import cota.events as events
    assert not hasattr(events, 'SkillReadEvent')
    assert not hasattr(cota, 'SkillReadEvent')
    event = skill_result('weather', text='Instructions', timestamp=123.5, event_id='read-1')
    snapshot = event.as_dict()
    assert snapshot['type'] == 'tool_result'
    assert snapshot['event_id'] == 'read-1'
    assert snapshot['timestamp'] == 123.5
    assert snapshot['payload']['resource'] == {
        'kind': 'skill', 'skill': 'weather', 'path': '/skills/weather/SKILL.md'}
    restored = Event.from_dict(snapshot)
    assert isinstance(restored, events.ToolResultEvent)
    assert restored.as_dict() == snapshot


@pytest.mark.parametrize("event", [
    UserUtterEvent("hello"), BotUtterEvent("answer"), skill_result("weather"),
    ToolResultEvent('read', result='instructions'),
    Event(type="run_finished", payload={"status": "completed"}),
])
def test_event_subclass_and_identity_roundtrip(event):
    restored = Event.from_dict(event.as_dict())
    assert type(restored) is type(event)
    assert restored.as_dict() == event.as_dict()


def test_dst_event_snapshot_roundtrip(dst, mock_agent):
    events = [
        UserUtterEvent("weather?"),
        Event("run_started", {}, run_id="weather-run"),
        skill_result("weather", path="/skills/weather/SKILL.md"),
        ToolResultEvent('read', result='instructions'),
        BotUtterEvent("city?"),
        UserUtterEvent("Beijing"),
        BotUtterEvent("sunny"),
    ]
    for event in events:
        dst.append_event(event)
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    snapshot = dst.as_dict()
    restored = DST.from_events(snapshot['session_id'], snapshot['events'], agent=mock_agent, revision=snapshot['revision'])
    assert restored.as_dict() == snapshot
    assert restored.latest_user_text() == "Beijing"
    assert restored.latest_bot_text() == "sunny"
    assert isinstance(restored.events[2], ToolResultEvent)
    restored.events[2].payload["resource"]["path"] = "different"
    assert snapshot["events"][2]["payload"]["resource"]["path"] == "/skills/weather/SKILL.md"

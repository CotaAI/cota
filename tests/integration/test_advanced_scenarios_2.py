"""Advanced integration tests (round 3) — untested framework paths.

DST serialization round-trips, MessageBus close semantics,
and sliding window compression invariants.

No real LLM API keys needed — all LLM calls are mocked.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from cota.processor import Processor
from cota.store import MemoryStore
from cota.message.message import Message
from cota.events import Event
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.events import (
    UserUtterEvent,
    BotUtterEvent,
)
from cota.channels.queue import MessageBus
from cota.channels.events import InboundMessage
from tests.conftest import MockAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(text, session_id="s1", sender_id="user1"):
    return Message(
        text=text,
        sender="user",
        sender_id=sender_id,
        receiver="bot",
        receiver_id="default_bot",
        session_id=session_id,
    )


async def _get_dst(store, session_id, agent) -> DST:
    dst = await store.load(session_id, agent=agent)
    assert dst is not None, f"No DST found for session {session_id}"
    return dst


def _events_of_type(dst, event_type):
    return [e for e in dst.events if e.type == event_type]


# ===========================================================================
# Scenario 17: LLM Error Recovery
# ===========================================================================

class TestLLMErrorRecovery:
    """LLM raises exception → BotUtterEvent with error message, no crash."""

    @pytest.mark.asyncio
    async def test_llm_exception_produces_error_bot_event(self):
        agent = MockAgent()
        agent._llm_mock.generate_chat = AsyncMock(
            side_effect=Exception("API timeout")
        )

        store = MemoryStore()
        processor = Processor(agent=agent, store=store)
        await processor.handle_message(_msg("Hello", session_id="err1"))

        dst = await _get_dst(store, "err1", agent)
        bot_events = _events_of_type(dst, "bot_utter")
        assert len(bot_events) >= 1

        error_text = bot_events[0].text
        assert "抱歉" in error_text or "错误" in error_text
        assert "API timeout" in error_text

        # No Skill document was read before the error.
        assert dst.active_skill is None


# ===========================================================================
# Scenario 18: LLM Error After a Tool Read
# ===========================================================================

class TestLLMErrorAfterTool:
    """Tool execution followed by model failure produces one durable error reply."""

    @pytest.mark.asyncio
    async def test_error_reply_delivered_once(self):
        from tests.test_pi_runtime import call
        agent = MockAgent()
        agent._llm_mock.generate_chat.side_effect = [
            {'tool_calls': [call('read', {'path': agent.skill_file('SearchWeb')}, 'read')]},
            Exception('LLM overloaded'),
        ]
        store = MemoryStore()
        bus = MessageBus()
        processor = Processor(agent=agent, store=store, message_bus=bus)
        inbound = InboundMessage(channel='web', sender_id='user1', chat_id='chat1', content='Do work')
        await processor.handle_inbound_message(inbound)
        dst = await _get_dst(store, inbound.session_key, agent)
        bot_events = _events_of_type(dst, 'bot_utter')
        assert len(bot_events) == 1
        assert '抱歉' in bot_events[0].text
        assert 'LLM overloaded' not in bot_events[0].text
        assert dst.execution['status'] == 'failed'
        outbound = await bus.consume_outbound(timeout=0.2)
        assert outbound.content == bot_events[0].text
        assert bus.outbound_size == 0
        await bus.close()


# ===========================================================================
# Scenario 24: Completed Question Round-trip
# ===========================================================================

class TestDSTQuestionRoundTrip:
    """Questions are normal completed turns that survive replay."""

    def test_question_roundtrip(self):
        agent = MockAgent()
        dst = DST(session_id="question1", agent=agent)
        dst.append_event(UserUtterEvent(text="help"))
        dst.append_event(Event('run_started', {
            'input_event_id': dst.latest_user_event.event_id,
        }, run_id='ask-run'))
        dst.append_event(skill_result('SearchWeb'))
        dst.append_event(BotUtterEvent('请问您需要什么帮助？'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        restored = DST.from_events(dst.session_id, dst.events, agent)
        assert restored.execution['status'] == 'completed'
        assert restored.latest_bot_text() == '请问您需要什么帮助？'
        assert restored.state_dict() == dst.state_dict()
        assert restored.active_skill == 'SearchWeb'
        assert 'paused_state' not in restored.state_dict()

    def test_new_input_starts_run_without_erasing_question(self):
        dst = DST(session_id="question2", agent=MockAgent())
        dst.append_event(Event('run_started', {}, run_id='ask-run'))
        dst.append_event(BotUtterEvent('Which city?'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        dst.append_event(UserUtterEvent('cancel and start another task'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='next'))
        restored = DST.from_events(dst.session_id, dst.events)
        assert restored.execution['status'] == 'running'
        assert restored.latest_bot_text() == 'Which city?'
        assert restored.state_dict() == dst.state_dict()


# ===========================================================================
# Scenario 25: MessageBus Close-Then-Consume
# ===========================================================================

class TestMessageBusCloseThenConsume:
    """close() before consume → returns None immediately."""

    @pytest.mark.asyncio
    async def test_consume_after_close_returns_none(self):
        bus = MessageBus()
        await bus.close()

        assert bus.is_closed

        result = await bus.consume_inbound(timeout=0.1)
        assert result is None

        result = await bus.consume_outbound(timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_publish_after_close_is_rejected(self):
        """A closed bus rejects publication and retains no undeliverable input."""
        bus = MessageBus()
        await bus.close()

        inbound = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="hi"
        )
        with pytest.raises(RuntimeError, match='closed'):
            await bus.publish_inbound(inbound)

        assert bus.inbound_size == 0
        result = await bus.consume_inbound(timeout=0.1)
        assert result is None


# ===========================================================================
# Scenario 26: MessageBus Close While Consuming (Timeout)
# ===========================================================================

class TestMessageBusCloseWhileConsuming:
    """Consume with timeout exits after close, doesn't hang."""

    @pytest.mark.asyncio
    async def test_consume_with_timeout_exits(self):
        bus = MessageBus()
        consumer = asyncio.create_task(bus.consume_inbound(timeout=10))
        await asyncio.sleep(0)
        assert not consumer.done()
        await bus.close()
        # Closure itself wakes the waiter, well before its own timeout.
        assert await asyncio.wait_for(consumer, timeout=0.2) is None

    @pytest.mark.asyncio
    async def test_is_empty_reflects_queue_state(self):
        bus = MessageBus()
        assert bus.is_empty()

        inbound = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="msg"
        )
        await bus.publish_inbound(inbound)
        assert not bus.is_empty()

        await bus.consume_inbound(timeout=0.1)
        assert bus.is_empty()


# ===========================================================================
# Scenario 27: Sliding Window Compression Invariants
# ===========================================================================

class TestPiContextBudget:
    """Cota commits Pi-selected prefixes and keeps original execution facts."""

    @pytest.mark.asyncio
    async def test_compression_preserves_current_tool_batch(self):
        from cota.runtime.pi_runtime import PiAgentRuntime
        agent = MockAgent()
        dst = DST('compact', agent)
        dst.append_event(UserUtterEvent('old' * 1000))
        dst.append_event(BotUtterEvent('old answer'))
        dst.append_event(UserUtterEvent('current'))
        dst.append_event(Event('run_started', {}, run_id='r'))
        dst.append_event(Event('tool_started', {
            'tool_call_id': 'a', 'tool': 'web_fetch', 'arguments': {'url': 'https://example.com'},
            'llm': {'request_id': 'q', 'request_sequence': 1, 'model': 'default', 'stop_reason': 'toolUse',
                    'message': {'content': [{'type': 'toolCall', 'id': 'a', 'name': 'web_fetch',
                                             'arguments': {'url': 'https://example.com'}}], 'stop_reason': 'toolUse'}},
        }, run_id='r'))
        dst.append_event(Event('tool_result', {'tool_call_id': 'a', 'tool': 'web_fetch', 'result': 'example data', 'status': 'success'}))
        runtime = PiAgentRuntime(agent, dst, 'compact')
        current = dst.context_messages[2:]
        messages = [{'role': 'system', 'content': 'current policy'}] + dst.context_messages
        agent._llm_mock.generate_chat.return_value = {'content': 'old summary'}
        projected = (await runtime._handle_request('compact', {
            'summary': 'old summary',
            'replaced_message_ids': [m['cotaEventId'] for m in dst.context_messages[:2]],
            'first_kept_id': current[0]['cotaEventId'],
        }))['messages']
        assert projected[1:] == current
        assert 'old summary' in projected[0]['content']
        assert len(messages[1]['content']) == 3000

    @pytest.mark.asyncio
    async def test_current_turn_too_large_is_not_discarded(self):
        from cota.runtime.pi_runtime import PiAgentRuntime
        agent = MockAgent()
        dst = DST('large', agent)
        agent._llm_mock.context_window = 2000
        agent.dialogue['compaction'] = {'reserve_tokens': 500, 'keep_recent_tokens': 100}
        dst.append_event(UserUtterEvent('x' * 40000))
        runtime = PiAgentRuntime(agent, dst, 'large')
        with pytest.raises(RuntimeError, match='cannot be compacted'):
            await runtime.run()
        agent._llm_mock.generate_chat.assert_not_awaited()
        assert len(dst.latest_user_text()) == 40000

    @pytest.mark.asyncio
    async def test_failed_summary_retains_original_messages(self):
        from cota.runtime.pi_runtime import PiAgentRuntime
        from copy import deepcopy
        agent = MockAgent()
        agent._llm_mock.context_window = 3000
        agent.dialogue['compaction'] = {'reserve_tokens': 1000, 'keep_recent_tokens': 200}
        agent._llm_mock.generate_chat.return_value = {'content': ''}
        dst = DST('failure', agent)
        dst.append_event(UserUtterEvent('old task'))
        dst.append_event(BotUtterEvent('x' * 16000))
        dst.append_event(UserUtterEvent('current'))
        runtime = PiAgentRuntime(agent, dst, 'failure')
        messages = dst.context_messages
        original = deepcopy(messages)
        with pytest.raises(RuntimeError, match='empty summary'):
            await runtime.run()
        assert messages == original
        assert not any(e.type == 'context_compaction' for e in dst.events)

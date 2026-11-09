"""Integration tests — end-to-end bot scenarios via Processor.

Each scenario mocks the LLM layer and verifies the full message flow:
  User message → Processor → PiAgentRuntime → DST events → response.

No real LLM API keys needed.
"""

import json
import asyncio
import pytest
from cota.events.resources import skill_read_name
from unittest.mock import AsyncMock

from cota.processor import Processor
from cota.store import MemoryStore
from cota.message.message import Message
from cota.dst import DST
from cota.channels.events import InboundMessage, OutboundMessage
from cota.channels.queue import MessageBus
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
# Scenario 1: Basic Q&A
# ===========================================================================

class TestBasicQA:
    """User sends a message, bot replies with text — no tools."""

    @pytest.mark.asyncio
    async def test_single_turn(self):
        agent = MockAgent()
        agent._llm_mock.generate_chat = AsyncMock(
            return_value={"content": "Hello! How can I help?", "tool_calls": []}
        )
        store = MemoryStore()
        processor = Processor(agent=agent, store=store)

        await processor.handle_message(_msg("Hi there"))

        dst = await _get_dst(store, "s1", agent)
        assert dst.latest_user_text() == "Hi there"
        assert dst.latest_bot_text() == "Hello! How can I help?"

        user_events = _events_of_type(dst, "user_utter")
        bot_events = _events_of_type(dst, "bot_utter")
        assert len(user_events) == 1
        assert len(bot_events) == 1

    @pytest.mark.asyncio
    async def test_non_bot_receiver_no_bot_turn(self):
        """Messages not addressed to 'bot' should be logged but not trigger a bot turn."""
        agent = MockAgent()
        store = MemoryStore()
        processor = Processor(agent=agent, store=store)

        msg = Message(
            text="Hello",
            sender="user",
            sender_id="u1",
            receiver="other_user",
            receiver_id="u2",
            session_id="s2",
        )
        await processor.handle_message(msg)

        dst = await _get_dst(store, "s2", agent)
        assert len(_events_of_type(dst, "user_utter")) == 1
        assert len(_events_of_type(dst, "bot_utter")) == 0


# ===========================================================================
# Scenario 2: Multi-turn Dialogue
# ===========================================================================

class TestMultiTurnDialogue:
    """Multiple messages in the same session — DST accumulates history."""

    @pytest.mark.asyncio
    async def test_three_turns(self):
        agent = MockAgent()
        call_count = 0

        async def varied_responses(**kwargs):
            nonlocal call_count
            call_count += 1
            replies = [
                "Hello!",
                "I can help with many things.",
                "Goodbye!",
            ]
            idx = min(call_count - 1, len(replies) - 1)
            return {"content": replies[idx], "tool_calls": []}

        agent._llm_mock.generate_chat = AsyncMock(side_effect=varied_responses)
        store = MemoryStore()

        for text in ["Hi", "What can you do?", "Bye"]:
            processor = Processor(agent=agent, store=store)
            await processor.handle_message(_msg(text, session_id="multi"))

        dst = await _get_dst(store, "multi", agent)
        user_events = _events_of_type(dst, "user_utter")
        bot_events = _events_of_type(dst, "bot_utter")
        assert len(user_events) == 3
        assert len(bot_events) == 3
        assert user_events[0].text == "Hi"
        assert user_events[2].text == "Bye"
        assert bot_events[2].text == "Goodbye!"


# ===========================================================================
# Scenario 3: Skill Document Reading
# ===========================================================================

class TestSkillRead:
    """LLM reads a Skill document, then responds."""

    @pytest.mark.asyncio
    async def test_read_records_trace(self):
        agent = MockAgent()
        call_count = 0

        async def skill_flow(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: LLM reads SearchWeb instructions
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc1",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({
                                "path": agent.skill_file("SearchWeb"),
                            }),
                        },
                    }],
                }
            # Second call: LLM uses the document to answer
            return {"content": "Here are the latest AI news.", "tool_calls": []}

        agent._llm_mock.generate_chat = AsyncMock(side_effect=skill_flow)
        store = MemoryStore()
        processor = Processor(agent=agent, store=store)

        await processor.handle_message(_msg("Search for AI news", session_id="skill1"))

        dst = await _get_dst(store, "skill1", agent)
        skill_events = [e for e in dst.events if skill_read_name(e)]
        assert len(skill_events) == 1
        assert skill_events[0].skill == "SearchWeb"
        assert dst.latest_bot_text() == "Here are the latest AI news."


# ===========================================================================
# Scenario 4: Plain Question and Follow-up
# ===========================================================================

class TestQuestionFollowup:
    """A text question completes one run; the answer starts the next run."""

    @pytest.mark.asyncio
    async def test_question_then_answer(self):
        agent = MockAgent()
        call_count = 0

        async def ask_flow(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # LLM reads the Skill first
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc1",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({
                                "path": agent.skill_file("SearchWeb"),
                            }),
                        },
                    }],
                }
            if call_count == 2:
                return {"content": "What topic should I search?", "tool_calls": []}
            # After resume, LLM gives final answer
            return {"content": "Found results for AI.", "tool_calls": []}

        agent._llm_mock.generate_chat = AsyncMock(side_effect=ask_flow)
        store = MemoryStore()

        # Turn 1: user sends message, bot asks a question
        proc1 = Processor(agent=agent, store=store)
        await proc1.handle_message(_msg("Search something", session_id="question1"))

        dst1 = await _get_dst(store, "question1", agent)
        assert dst1.execution['status'] == 'completed'
        assert "What topic" in dst1.latest_bot_text()

        # Turn 2: user answers the question, bot continues
        proc2 = Processor(agent=agent, store=store)
        await proc2.handle_message(_msg("AI", session_id="question1"))

        dst2 = await _get_dst(store, "question1", agent)
        # The next user message starts a new run, which completes normally.
        assert dst2.execution['status'] == 'completed'
        assert dst2.active_skill == "SearchWeb"
        assert dst2.latest_bot_text() == "Found results for AI."


# ===========================================================================
# Scenario 5: MessageBus Path
# ===========================================================================

class TestMessageBusPath:
    """InboundMessage → MessageBus → Processor → OutboundMessage."""

    @pytest.mark.asyncio
    async def test_inbound_to_outbound(self):
        agent = MockAgent()
        agent._llm_mock.generate_chat = AsyncMock(
            return_value={"content": "Bus reply!", "tool_calls": []}
        )
        store = MemoryStore()
        bus = MessageBus()

        processor = Processor(agent=agent, store=store, message_bus=bus)

        inbound = InboundMessage(
            channel="web",
            sender_id="user1",
            chat_id="chat1",
            content="Hello via bus",
        )

        await processor.handle_inbound_message(inbound)

        # The outbound queue should have the bot's reply
        outbound = await asyncio.wait_for(
            bus.consume_outbound(timeout=2.0), timeout=3.0
        )
        assert outbound is not None
        assert isinstance(outbound, OutboundMessage)
        assert outbound.content == "Bus reply!"
        assert outbound.channel == "web"
        assert outbound.chat_id == "chat1"

        # DST should also be persisted
        dst = await _get_dst(store, inbound.session_key, agent)
        assert dst.latest_user_text() == "Hello via bus"
        assert dst.latest_bot_text() == "Bus reply!"

        await bus.close()


# ===========================================================================
# Scenario 6: Final Response Delivery
# ===========================================================================

class TestFinalResponseDelivery:
    """The model final becomes one durable bot utterance and one delivery."""

    @pytest.mark.asyncio
    async def test_final_response_delivered_once_after_persistence(self):
        from tests.test_pi_runtime import call
        agent = MockAgent()
        agent._llm_mock.generate_chat.side_effect = [
            {'tool_calls': [call('read', {'path': agent.skill_file('SearchWeb')}, 'read')]},
            {'content': 'Search complete.'},
        ]
        store = MemoryStore()
        delivered = []

        async def channel_callback(message):
            saved = await _get_dst(store, 'final1', agent)
            assert saved.latest_bot_text() == 'Search complete.'
            delivered.append(message)

        processor = Processor(agent=agent, store=store)
        processor.set_channel_callback(channel_callback)
        await processor.handle_message(_msg('Search', session_id='final1'))
        dst = await _get_dst(store, 'final1', agent)
        assert dst.execution['status'] == 'completed'
        assert len(_events_of_type(dst, 'bot_utter')) == 1
        assert len(delivered) == 1
        assert agent._llm_mock.generate_chat.await_count == 2

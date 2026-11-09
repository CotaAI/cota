"""Tests for Processor (Event-based)."""

import pytest
from cota.processor import Processor
from cota.store import MemoryStore
from cota.message.message import Message
from cota.dst import DST
from cota.events import UserUtterEvent


@pytest.mark.asyncio
class TestProcessor:
    async def test_handle_message_records_user_event(self, mock_agent):
        store = MemoryStore()
        mock_agent.store = store
        processor = Processor(agent=mock_agent, store=store)

        msg = Message(
            text="hello",
            sender="user",
            sender_id="u1",
            receiver="bot",
            receiver_id="default_bot",
            session_id="s1",
        )

        await processor.handle_message(msg)

        data = await store.export_session("s1")
        assert data is not None
        events = data["events"]
        user_events = [e for e in events if e["type"] == 'user_utter']
        assert len(user_events) >= 1
        assert user_events[0]["payload"]["text"] == "hello"

    async def test_handle_message_non_bot_receiver(self, mock_agent):
        store = MemoryStore()
        mock_agent.store = store
        processor = Processor(agent=mock_agent, store=store)

        msg = Message(
            text="hello",
            sender="user",
            sender_id="u1",
            receiver="other_user",
            receiver_id="u2",
            session_id="s1",
        )

        await processor.handle_message(msg)

        data = await store.export_session("s1")
        events = data["events"]
        # Should only have user event, no bot events
        assert all(e["type"] != 'bot_utter' for e in events)

    async def test_get_tracker_creates_new(self, mock_agent):
        store = MemoryStore()
        processor = Processor(agent=mock_agent, store=store)

        tracker = await processor.get_tracker("new_session")
        assert tracker.session_id == "new_session"
        assert len(tracker.events) == 0

    async def test_get_tracker_restores(self, mock_agent):
        store = MemoryStore()
        processor = Processor(agent=mock_agent, store=store)

        # Save initial state
        dst = DST(session_id="s1", agent=mock_agent)
        dst.append_event(UserUtterEvent(text="first"))
        await store.save(dst)

        # Retrieve
        tracker = await processor.get_tracker("s1")
        assert tracker.latest_user_text() == "first"

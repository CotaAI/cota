"""Tests for Store (session-level storage)."""

import pytest
from cota.store import MemoryStore
from cota.dst import DST
from cota.events import UserUtterEvent, BotUtterEvent, ToolResultEvent


@pytest.mark.asyncio
class TestMemoryStore:
    async def test_save_and_export(self, mock_agent):
        store = MemoryStore()
        dst = DST(session_id="s1", agent=mock_agent)
        dst.append_event(UserUtterEvent(text="hello"))
        dst.append_event(BotUtterEvent(text="hi"))

        await store.save(dst)

        data = await store.export_session("s1")
        assert data is not None
        assert data["session_id"] == "s1"
        assert len(data["events"]) > 0

    async def test_export_missing(self, mock_agent):
        store = MemoryStore()
        data = await store.export_session("nonexistent")
        assert data is None

    async def test_overwrite(self, mock_agent):
        store = MemoryStore()
        dst = DST(session_id="s1", agent=mock_agent)
        dst.append_event(UserUtterEvent(text="first"))
        await store.save(dst)

        dst.append_event(BotUtterEvent(text="response"))
        await store.save(dst)

        data = await store.export_session("s1")
        events = data["events"]
        assert len(events) >= 2

    async def test_roundtrip(self, mock_agent):
        store = MemoryStore()
        dst = DST(session_id="s1", agent=mock_agent, user_id="u1")
        dst.append_event(UserUtterEvent(text="hello"))
        dst.append_event(ToolResultEvent(tool='exec', result='ok'))
        dst.append_event(BotUtterEvent(text="done"))

        await store.save(dst)

        data = await store.export_session("s1")
        assert data["session_id"] == "s1" and data["events"]
        dst2 = await store.load('s1', agent=mock_agent)
        assert dst2.session_id == "s1"
        assert dst2.user_id == "u1"
        assert dst2.latest_user_text() == "hello"
        assert dst2.latest_bot_text() == "done"
        assert dst2.state_dict() == dst.state_dict()

    async def test_latest_utter(self, mock_agent):
        store = MemoryStore()

        dst1 = DST(session_id="s1", agent=mock_agent)
        dst1.append_event(UserUtterEvent(text="q1"))
        dst1.append_event(BotUtterEvent(text="a1"))
        await store.save(dst1)

        dst2 = DST(session_id="s2", agent=mock_agent)
        dst2.append_event(UserUtterEvent(text="q2"))
        await store.save(dst2)

        utters = await store.latest_utter(["s1", "s2"])
        assert len(utters) == 2

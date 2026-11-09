"""Advanced integration tests — complex bot scenarios for Cota 2.0 framework.

max iterations, and service-mode security.

No real LLM API keys needed — all LLM calls are mocked.
"""

import json
import asyncio
import time
import pytest
from cota.events.resources import skill_read_name
from unittest.mock import AsyncMock

from cota.processor import Processor
from cota.store import MemoryStore
from cota.message.message import Message
from cota.dst import DST
from cota.events import (
    UserUtterEvent,
)
from cota.executor.scheduler import (
    SchedulerService,
)
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
# Scenario 7: Multi-City Weather (Sequential Skill Calls)
# ===========================================================================

class TestMultiCityWeather:
    """Repeated Skill reads retain both city results and the final response."""

    @pytest.mark.asyncio
    async def test_two_sequential_skill_calls(self):
        agent = MockAgent()
        call_count = 0

        async def multi_city_flow(**kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Read the Skill for the Beijing query
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
                # Simulate an weather_lookup tool call
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc2",
                        "function": {
                            "name": "weather_lookup",
                            "arguments": json.dumps({
                                "url": "https://wttr.in/Beijing?format=j1",
                            }),
                        },
                    }],
                }
            if call_count == 3:
                # Read the same Skill again for the Shanghai query
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc3",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({
                                "path": agent.skill_file("SearchWeb"),
                            }),
                        },
                    }],
                }
            if call_count == 4:
                # Simulate a second city tool call
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc4",
                        "function": {
                            "name": "weather_lookup",
                            "arguments": json.dumps({
                                "url": "https://wttr.in/Shanghai?format=j1",
                            }),
                        },
                    }],
                }
            # Final answer comparing both cities
            return {
                "content": "北京25°C晴，上海28°C多云。上海更适合旅游。",
                "tool_calls": [],
            }

        agent._llm_mock.generate_chat = AsyncMock(side_effect=multi_city_flow)

        # Register weather_lookup as a mock tool
        from cota.executor.tools.base import Tool

        class MockHttpTool(Tool):
            @property
            def name(self): return "weather_lookup"
            @property
            def description(self): return "HTTP request"
            @property
            def parameters(self): return {"type": "object", "properties": {}}
            @property
            def category(self): return "network"

            async def execute(self, **kwargs):
                url = kwargs.get("url", "")
                if "Beijing" in url:
                    return {"current_condition": [{"temp_C": "25", "weatherDesc": [{"value": "Sunny"}]}]}
                return {"current_condition": [{"temp_C": "28", "weatherDesc": [{"value": "Cloudy"}]}]}

        agent._tool_registry.register(MockHttpTool())

        store = MemoryStore()
        processor = Processor(agent=agent, store=store)
        await processor.handle_message(_msg("比较北京和上海天气", session_id="multi_city"))

        dst = await _get_dst(store, "multi_city", agent)

        read_events = [e for e in dst.events if skill_read_name(e)]
        assert [e.skill for e in read_events] == ["SearchWeb", "SearchWeb"]
        assert dst.active_skill == "SearchWeb"
        event_types = [e.type for e in dst.events if (skill_read_name(e) or e.type == 'bot_utter')]
        assert event_types == ["tool_result", "tool_result", "bot_utter"]
        tool_results = [m['content'] for m in
                        agent._llm_mock.generate_chat.call_args.kwargs['messages']
                        if m['role'] == 'tool']
        assert any('25' in result and 'Sunny' in result for result in tool_results)
        assert any('28' in result and 'Cloudy' in result for result in tool_results)

        # Final bot text
        assert "上海" in dst.latest_bot_text()
        assert "北京" in dst.latest_bot_text()


# ===========================================================================
# Scenario 8: Skill Read Trace Persistence
# ===========================================================================

class TestSkillReadPersistence:
    """A completed response preserves the latest successfully read Skill label."""

    @pytest.mark.asyncio
    async def test_read_trace_retained_after_response(self):
        agent = MockAgent()
        call_count = 0

        async def read_flow(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
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
            # Text response ends the turn
            return {"content": "Search complete.", "tool_calls": []}

        agent._llm_mock.generate_chat = AsyncMock(side_effect=read_flow)
        store = MemoryStore()
        processor = Processor(agent=agent, store=store)
        await processor.handle_message(_msg("Search", session_id="lifecycle1"))

        dst = await _get_dst(store, "lifecycle1", agent)

        reads = [e for e in dst.events if skill_read_name(e)]
        assert len(reads) == 1
        assert reads[0].skill == "SearchWeb"
        assert dst.active_skill == "SearchWeb"
        assert dst.execution['status'] == 'completed'

        # Bot event recorded
        assert dst.latest_bot_text() == "Search complete."


# ===========================================================================
# ===========================================================================



# ===========================================================================
# ===========================================================================



# ===========================================================================
# Scenario 11: Customer Service Multi-Step Flow
# ===========================================================================

class TestCustomerServiceFlow:
    """Skill reading and a plain question persist across completed turns."""

    @pytest.mark.asyncio
    async def test_read_question_followup_response(self):
        agent = MockAgent()
        call_count = 0

        async def cs_flow(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Read customer service instructions
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
                return {"content": "请提供您的订单号", "tool_calls": []}
            # After resume with order number, complete
            return {
                "content": "订单 ORD-123 已提交退款申请，预计3天内到账。",
                "tool_calls": [],
            }

        agent._llm_mock.generate_chat = AsyncMock(side_effect=cs_flow)
        store = MemoryStore()

        # Turn 1: User requests refund → bot asks for order number
        proc1 = Processor(agent=agent, store=store)
        await proc1.handle_message(_msg("我要退款", session_id="cs1"))

        dst1 = await _get_dst(store, "cs1", agent)
        assert dst1.execution['status'] == 'completed'
        assert "订单号" in dst1.latest_bot_text()
        assert dst1.active_skill == "SearchWeb"

        # Turn 2: User provides order number → bot completes
        proc2 = Processor(agent=agent, store=store)
        await proc2.handle_message(_msg("ORD-123", session_id="cs1"))

        dst2 = await _get_dst(store, "cs1", agent)

        # The new run has completed
        assert dst2.execution['status'] == 'completed'

        # Completing a response leaves the last-read trace label intact.
        assert dst2.active_skill == "SearchWeb"
        assert len([e for e in dst2.events if skill_read_name(e)]) == 1

        # Bot response includes order number
        assert "ORD-123" in dst2.latest_bot_text()


# ===========================================================================
# Scenario 12: Scheduler Job Creation and Fire
# ===========================================================================

class TestSchedulerJobCreateAndFire:
    """Create an immediate job, tick, verify callback fires and auto-deletes."""

    @pytest.mark.asyncio
    async def test_add_immediate_job_fires(self, tmp_path, monkeypatch):
        from cota.executor.scheduler.store import JobStore
        callback_results = []

        async def on_fire(job):
            callback_results.append(job.name)

        store = JobStore(str(tmp_path / 'jobs.json'))
        service = SchedulerService(store=store)
        service.set_callback(on_fire)

        # Advance a controlled clock past a valid scheduled time; no real sleep.
        now = time.time()
        monkeypatch.setattr('cota.executor.scheduler.service.time.time', lambda: now)
        job = await service.add_job(
            name="test_reminder",
            schedule={"type": "at", "at": "+1s"},
            payload={"text": "提醒测试"},
        )

        assert job is not None
        assert job.name == "test_reminder"

        now += 2
        await service._tick()
        await asyncio.gather(*service._callback_tasks)
        assert callback_results == ["test_reminder"]
        assert store.get(job.id) is None
        assert JobStore(store.path).get(job.id) is None


# ===========================================================================
# Scenario 15: Multiple Skill Documents in Context
# ===========================================================================

class TestSkillCompositionContext:
    """Reading another Skill keeps both documents in tool-result history."""

    @pytest.mark.asyncio
    async def test_reads_preserve_both_documents_and_latest_label(self):
        from cota.runtime.pi_runtime import PiAgentRuntime
        from tests.test_pi_runtime import call
        agent = MockAgent()
        agent.add_skill('OtherSkill', 'new skill SOP')
        store = MemoryStore()
        dst = DST('switch', agent)
        dst.append_event(UserUtterEvent('test'))
        agent._llm_mock.generate_chat.side_effect = [
            {'tool_calls': [call('read', {'path': agent.skill_file('SearchWeb')}, 'first')]},
            {'tool_calls': [call('read', {'path': agent.skill_file('OtherSkill')}, 'second')]},
            {'content': 'done'},
        ]
        await PiAgentRuntime(agent, dst, 'switch', checkpoint=store.save).run()
        messages = agent._llm_mock.generate_chat.call_args.kwargs['messages']
        assert 'new skill SOP' not in messages[0]['content']
        results = [m['content'] for m in messages if m['role'] == 'tool']
        assert any('new skill SOP' in result for result in results)
        assert any('Use the available tools to search the web.' in result for result in results)
        assert {m['tool_call_id'] for m in messages if m['role'] == 'tool'} == {'first', 'second'}
        assert [e.skill for e in dst.events if skill_read_name(e)] == ['SearchWeb', 'OtherSkill']
        assert dst.active_skill == 'OtherSkill'
        stored = await store.export_session('switch')
        assert len([e for e in stored['events'] if e['type'] == 'tool_result']) == 2



# ===========================================================================
# Scenario 16: Max Iterations Fallback
# ===========================================================================

class TestMaxIterationsFallback:
    """Verify _on_max_iterations fires with fallback BotUtterEvent when loop exhausts."""

    @pytest.mark.asyncio
    async def test_max_iterations_produces_fallback(self):
        agent = MockAgent()
        agent.dialogue["max_iterations"] = 2  # Very low limit

        # LLM always returns tool calls, never text → will hit max iterations
        async def infinite_tools(**kwargs):
            return {
                "content": "",
                "tool_calls": [{
                    "id": f"tc_{time.time()}",
                    "function": {
                        "name": "read",
                        "arguments": json.dumps({
                            "path": agent.skill_file("SearchWeb"),
                        }),
                    },
                }],
            }

        agent._llm_mock.generate_chat = AsyncMock(side_effect=infinite_tools)
        store = MemoryStore()
        processor = Processor(agent=agent, store=store)

        await processor.handle_message(_msg("Do something", session_id="maxiter1"))

        dst = await _get_dst(store, "maxiter1", agent)

        # Should have a fallback bot event
        bot_events = _events_of_type(dst, "bot_utter")
        assert len(bot_events) >= 1

        fallback_text = bot_events[-1].text
        assert "最大步骤限制" in fallback_text or "max" in fallback_text.lower()

"""Migration contract: Pi is the only model/tool execution engine."""
import importlib.util

import pytest

from cota.dst import DST
from cota.processor import Processor
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore


def test_agent_rejects_legacy_at_configuration_load(tmp_path):
    from cota.agent import Agent
    (tmp_path / 'agent.yml').write_text('dialogue:\n  runtime: legacy\n')
    (tmp_path / 'endpoints.yml').write_text('{}')
    with pytest.raises(ValueError, match='removed.*pi'):
        Agent.load_from_path(str(tmp_path))


def test_pi_is_independent_of_removed_python_engines():
    assert PiAgentRuntime.__bases__ == (object,)
    import cota.runtime as runtime
    assert runtime.__all__ == ['PiAgentRuntime']
    for module in ('cota.runtime.base', 'cota.runtime.agent_runtime', 'cota.executor.skill',
                   'cota.executor.base', 'cota.executor.tool_servers.runtime',
                   'cota.executor.tool_servers.loader', 'cota.executor.tools.read_skill',
                   'cota.executor.memory', 'cota.debugger'):
        assert importlib.util.find_spec(module) is None


@pytest.mark.asyncio
async def test_legacy_runtime_is_rejected_with_migration_instruction(mock_agent):
    mock_agent.dialogue['runtime'] = 'legacy'
    processor = Processor(agent=mock_agent, store=MemoryStore())
    processor.dst = DST('s', mock_agent)
    with pytest.raises(ValueError, match='removed.*pi'):
        await processor._create_runtime('s')

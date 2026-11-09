"""Shared fixtures for COTA test suite."""

import pytest
from unittest.mock import AsyncMock

from cota.executor.tools import ToolRegistry
from pathlib import Path
import tempfile


# ── Minimal mock Agent ──

class MockAgent:
    """Lightweight Agent mock for unit tests that don't need real config loading."""

    def __init__(self, name="test_bot", description="A test bot"):
        self.name = name
        self.description = description
        self.dialogue = {
            "llm": "default",
            "max_tokens": 500,
            "max_iterations": 15,
        }
        self.llms = {
            "default": {"model": "test-model", "type": "openai", "key": "sk-test"}
        }
        from cota.policy import PolicyCatalog, AllPolicy
        self.policy = AllPolicy(PolicyCatalog())
        self.knowledge = None
        self.is_team = False
        self.agents = {}
        self.store = None
        self.user_memory = None

        # Real Skill files, discovered and read by Pi rather than a Python parser.
        self._skill_directory = tempfile.TemporaryDirectory(prefix='cota-test-skills-')
        self.config_path = self._skill_directory.name
        self.workspace_path = str(Path(self.config_path) / 'workspace')
        Path(self.workspace_path).mkdir()
        self.skill_paths = [str(Path(self.config_path) / 'skills')]
        self.add_skill('SearchWeb', 'Use the available tools to search the web.')

        # Tool registry
        self._tool_registry = ToolRegistry()

        self._llm_mock = AsyncMock()
        self._llm_mock.generate_chat = AsyncMock(
            return_value={"content": "hello", "tool_calls": []}
        )

    def llm_instance(self, name=None):
        return self._llm_mock

    def get_tool_registry(self):
        return self._tool_registry

    def skill_file(self, name):
        return str(Path(self.skill_paths[0]) / name / 'SKILL.md')

    def add_skill(self, name, content):
        path = Path(self.skill_file(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\nname: {name}\ndescription: Instructions for {name}\n---\n{content}\n')
        return str(path)

    def create_processor(self):
        from cota.processor import Processor
        from cota.store import MemoryStore
        if not self.store:
            self.store = MemoryStore()
        return Processor(agent=self, store=self.store)


@pytest.fixture
def mock_agent():
    agent = MockAgent()
    try:
        yield agent
    finally:
        agent._skill_directory.cleanup()


# ── DST fixture ──

@pytest.fixture
def make_dst(mock_agent):
    """Factory fixture that creates a fresh DST."""
    from cota.dst import DST

    def _make(session_id="test_session"):
        return DST(session_id=session_id, agent=mock_agent)

    return _make


@pytest.fixture
def dst(make_dst):
    return make_dst()


# ── Store fixtures ──

@pytest.fixture
def memory_store():
    from cota.store import MemoryStore
    return MemoryStore()

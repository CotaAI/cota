"""Knowledge fallbacks must preserve context, stop on success and propagate cancellation."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.knowledge.knowledge import CompositeKnowledge, Knowledge, KnowledgeFactory
from cota.knowledge.llm_knowledge import LLMKnowledge


class StubKnowledge(Knowledge):
    def __init__(self, result='', error=None):
        super().__init__()
        self.retrieve = AsyncMock(return_value=result, side_effect=error)

    async def retrieve(self, query, context=None):
        raise AssertionError('replaced by the controlled boundary')


async def test_fallback_preserves_query_context_and_stops_after_first_usable_result():
    failed = StubKnowledge(error=OSError('retrieval unavailable'))
    empty, usable, unused = StubKnowledge('  '), StubKnowledge('  useful fact  '), StubKnowledge('unused')
    knowledge = CompositeKnowledge([failed, empty, usable, unused])
    context = {'session_id': 'one'}
    assert await knowledge.process_query('question', context) == 'useful fact'
    for strategy in (failed, empty, usable):
        strategy.retrieve.assert_awaited_once_with('question', context)
    unused.retrieve.assert_not_awaited()


async def test_all_fallbacks_unavailable_returns_empty_and_cancellation_is_not_swallowed():
    assert await CompositeKnowledge([StubKnowledge(error=OSError()), StubKnowledge(' ')]).process_query('q') == ''
    with pytest.raises(asyncio.CancelledError):
        await CompositeKnowledge([StubKnowledge(error=asyncio.CancelledError())]).process_query('q')


@pytest.mark.parametrize('config', [None, []])
def test_disabled_knowledge(config):
    assert KnowledgeFactory.create(config) is None


@pytest.mark.parametrize('config', [[{}], [{'type': 'missing'}], [{'type': 'llm'}], ['llm']])
def test_invalid_knowledge_fails_during_configuration(config):
    with pytest.raises(ValueError):
        KnowledgeFactory.create(config)


def test_single_and_composite_factory_preserve_strategy_order():
    one = KnowledgeFactory.create([{'type': 'llm', 'llm': 'first'}])
    assert isinstance(one, LLMKnowledge) and one.llm == 'first'
    many = KnowledgeFactory.create([{'type': 'llm', 'llm': name} for name in ('first', 'second')])
    assert isinstance(many, CompositeKnowledge)
    assert [strategy.llm for strategy in many.strategies] == ['first', 'second']


async def test_knowledge_uses_latest_five_messages_and_missing_agent_does_not_call_model():
    model = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': 'fact'}))
    knowledge = LLMKnowledge({'llm': 'default', 'prompt': '{{query}}\n{{history}}'})
    history = [{'role': 'user', 'content': f'message-{index}'} for index in range(7)]
    context = {'agent': SimpleNamespace(llm_instance=lambda name: model),
               'dst': SimpleNamespace(extract_messages=lambda: history)}
    assert await knowledge.retrieve('question') == ''
    model.generate_chat.assert_not_awaited()
    assert await knowledge.retrieve('question', context) == 'fact'
    prompt = model.generate_chat.call_args.kwargs['messages'][0]['content']
    assert 'message-0' not in prompt and 'message-1' not in prompt
    assert all(f'message-{index}' in prompt for index in range(2, 7))

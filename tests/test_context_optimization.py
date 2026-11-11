"""Regressions for Pi budgeting, durable compaction and focused guidance."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.llm.openai import OpenAIClient
from cota.policy import PolicyCatalog


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
@pytest.mark.parametrize('pressure', ['count', 'bytes'])
async def test_image_only_budget_projects_without_unnecessary_compaction_or_evidence_loss(mock_agent, tmp_path, backend, pressure):
    import base64
    import io
    Image = pytest.importorskip('PIL.Image')
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.executor.tools import FunctionTool
    from cota.runtime.pi_runtime import PiAgentRuntime
    from cota.store import MemoryStore, SQLStore
    from tests.test_pi_runtime import call

    output = io.BytesIO()
    Image.new('RGB', (64, 64), 'red').save(output, format='PNG')
    image_bytes = output.getvalue()
    encoded = base64.b64encode(image_bytes).decode()
    mock_agent._llm_mock.context_window = 1000000
    mock_agent.dialogue['compaction'] = ({'max_images': 2} if pressure == 'count'
                                        else {'max_image_bytes': 2 * len(image_bytes)})
    mock_agent.get_tool_registry().register(FunctionTool('picture', 'Read an image',
        {'type': 'object', 'properties': {}},
        lambda: {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': encoded}]}))
    decisions = iter([{'tool_calls': [call('picture', {}, f'image{i}')]} for i in range(3)]
                     + [{'content': 'Saved the images for review.'}])
    requests, summaries = [], []

    async def model(**kwargs):
        if 'context summarization assistant' in kwargs['messages'][0]['content']:
            summaries.append(kwargs)
            assert encoded not in str(kwargs)
            return {'content': 'Create a picture book. Earlier images were read; their visual quality has not been confirmed.'}
        requests.append(kwargs)
        return next(decisions)

    mock_agent._llm_mock.generate_chat.side_effect = model
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'images.db'))
    dst = DST('images', mock_agent)
    dst.append_event(UserUtterEvent('Create a picture book.'))
    try:
        await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save, store=store).run()
        assert dst.execution['status'] == 'completed'
        assert len(requests) == 4 and not summaries
        assert not any(e.type == 'context_compaction' for e in dst.events)
        images = [b for m in requests[-1]['messages'] if isinstance(m.get('content'), list)
                  for b in m['content'] if b['type'] == 'image_url']
        assert len(images) == 1
        assert len(base64.b64decode(images[0]['image_url']['url'].split(',', 1)[1])) == len(image_bytes)
        results = [e for e in dst.events if e.type == 'tool_result']
        assert len(results) == 3
        assert all(e.payload['content'][0]['data'] == encoded for e in results)
        assert all(event.event_id in str(requests[-1]['messages']) for event in results[:-1])
        assert 'sha256:' in str(requests[-1]['messages']) and 're-read' in str(requests[-1]['messages'])
        restored = await store.load(dst.session_id, mock_agent)
        replay = DST.from_events(dst.session_id, dst.events, agent=mock_agent, run_metadata=dst.run_metadata)
        assert restored.state_dict() == replay.state_dict() == dst.state_dict()
    finally:
        if backend == 'sqlite':
            store.engine.dispose()


def test_request_size_ignores_image_encoding_and_provider_usage_is_not_an_estimate():
    from cota.llm.metrics import request_metrics
    value = request_metrics({'messages': [
        {'role': 'system', 'content': 'rules'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'look'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'a' * 2000000}}]},
    ], 'tools': []})
    assert value['text_chars'] == 9
    assert value['images'] == 1
    assert value['inline_image_bytes'] == 1500000
    assert value['sections']['system'] == 5
    assert value['sections']['user'] == 4


@pytest.mark.asyncio
async def test_provider_usage_survives_outside_debug():
    client = OpenAIClient('test', 'https://example.invalid', 'test')
    client.client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='done', tool_calls=None), finish_reason='stop')],
        usage=SimpleNamespace(prompt_tokens=40000, completion_tokens=2000, total_tokens=42000,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=30000))))
    try:
        result = await client.generate_chat([{'role': 'user', 'content': 'hello'}])
        assert result['usage']['input'] == 10000
        assert result['usage']['cacheRead'] == 30000
        assert result['usage']['totalTokens'] == 42000
    finally:
        await client.close()


def test_focused_policy_keeps_branch_condition_and_omits_later_dialogue():
    catalog = PolicyCatalog([{'name': 'order', 'steps': [
        {'user': 'Where is my order?'},
        {'bot': [{'thought': 'Find the order'}, {'skills': ['lookup']}]},
        {'bot': [{'result': 'Order missing'}, {'thought': 'Ask for the correct number'}, {'reply': 'Check your order number'}]},
        {'user': 'Cancel it instead'},
        {'bot': [{'thought': 'UNRELATED_LATER_CANCELLATION'}, {'reply': 'Cancelled'}]},
    ]}])
    value = catalog.guidance(['lookup'], [], matches=[{'name': 'order', 'status': 'applicable', 'step': 2, 'evidence': ['r']}])
    assert 'Order missing' in value['text']
    assert 'Where is my order?' in value['text']
    assert 'Ask for the correct number' in value['text']
    assert 'UNRELATED_LATER_CANCELLATION' not in value['text']
    assert [t['step'] for t in value['thoughts']] == [2]


def test_focused_policy_keeps_the_question_that_a_short_user_reply_answers():
    catalog = PolicyCatalog([{'name': 'confirm', 'steps': [
        {'user': 'Cancel my order'},
        {'bot': [{'thought': 'OLD_GUIDANCE'}, {'reply': 'Cancel the entire order, including the gift?'}]},
        {'user': 'Yes'},
        {'bot': [{'thought': 'Cancel all items after confirmation'}, {'skills': ['cancel']}]},
    ]}])
    value = catalog.guidance(['cancel'], [], matches=[{'name': 'confirm', 'status': 'conditional', 'step': 3}])
    assert 'including the gift' in value['text']
    assert 'OLD_GUIDANCE' not in value['text']


@pytest.mark.asyncio
async def test_actual_usage_survives_event_checkpoint_and_replay(mock_agent):
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    from cota.store import MemoryStore
    from tests.test_pi_runtime import call
    usage = {'input': 1000, 'output': 100, 'cacheRead': 5000, 'cacheWrite': 0, 'totalTokens': 6100,
             'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0}}
    store = MemoryStore()
    dst = DST('usage', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})], 'usage': usage},
        {'content': 'done', 'usage': usage},
    ]
    await PiAgentRuntime(mock_agent, dst, 'usage', checkpoint=store.save).run()
    restored = await store.load('usage', agent=mock_agent)
    assert [m['usage']['totalTokens'] for m in restored.context_messages if m['role'] == 'assistant'] == [6100, 6100]
    assert restored.context_messages == dst.context_messages


@pytest.mark.asyncio
async def test_pi_receives_provider_model_id_instead_of_endpoint_alias(mock_agent):
    import sys
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent._llm_mock.name = 'default'
    mock_agent._llm_mock.client = SimpleNamespace(model='actual-provider-model')
    dst = DST('model', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    runtime = PiAgentRuntime(mock_agent, dst, 'model')
    runtime._bridge.run = AsyncMock(return_value={'status': 'completed'})
    await runtime.run()
    assert runtime._bridge.run.call_args.args[0]['model']['id'] == 'actual-provider-model'
    assert runtime._bridge.run.call_args.args[0]['pythonExecutable'] == sys.executable


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_single_turn_long_chain_compacts_and_keeps_image_for_next_request(mock_agent, tmp_path, backend):
    import base64
    import io
    import random
    Image = pytest.importorskip('PIL.Image')
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.executor.tools import FunctionTool
    from cota.runtime.pi_runtime import PiAgentRuntime
    from cota.store import MemoryStore, SQLStore
    from tests.test_pi_runtime import call

    image = Image.frombytes('RGB', (768, 768), random.Random(0).randbytes(768 * 768 * 3))
    output = io.BytesIO()
    image.save(output, format='PNG')
    encoded = base64.b64encode(output.getvalue()).decode()
    mock_agent._llm_mock.context_window = 5000
    mock_agent.dialogue['compaction'] = {'reserve_tokens': 1000, 'keep_recent_tokens': 1000}
    schema = {'type': 'object', 'properties': {}}
    mock_agent.get_tool_registry().register(FunctionTool('long_source', 'Read long fixture', schema,
        lambda: {'content': [{'type': 'text', 'text': 'a' * 10000}]}))
    mock_agent.get_tool_registry().register(FunctionTool('picture', 'Return actual fixture image', schema,
        lambda: {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': encoded}]}))
    dialogue = iter([{'tool_calls': [call('long_source', {}, 'long')]},
                     {'tool_calls': [call('picture', {}, 'image')]}, {'content': 'image reviewed'}])
    seen, summaries = [], []

    async def model(**kwargs):
        if 'context summarization assistant' in kwargs['messages'][0]['content']:
            summaries.append(kwargs)
            assert encoded not in str(kwargs)
            return {'content': 'Original request: make a picture book. The long source was read; inspect the image next.'}
        seen.append(kwargs)
        return next(dialogue)

    mock_agent._llm_mock.generate_chat.side_effect = model
    store = MemoryStore(snapshot_interval=2) if backend == 'memory' else SQLStore(db=str(tmp_path / 'image.db'), snapshot_interval=2)
    dst = DST('image', mock_agent)
    dst.append_event(UserUtterEvent('Make a picture book.'))
    try:
        await PiAgentRuntime(mock_agent, dst, 'image', checkpoint=store.save, store=store).run()
        assert dst.execution['status'] == 'completed'
        assert len(summaries) == 1 and len(seen) == 3
        assert any(e.type == 'context_compaction' for e in dst.events)
        assert any(encoded in str(m) for m in seen[-1]['messages'])
        assert 'a' * 10000 not in str(seen[-1]['messages'])
        assert next(e for e in dst.events if e.type == 'tool_result' and e.tool == 'long_source').payload['result']
        restored = await store.load('image', agent=mock_agent)
        replayed = DST.from_events('image', [e.as_dict() for e in dst.events], agent=mock_agent,
                                   run_metadata=dst.run_metadata)
        assert restored.state_dict() == replayed.state_dict() == dst.state_dict()
    finally:
        if backend == 'sqlite':
            store.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_large_old_image_bytes_leave_wire_without_compaction_and_replay(mock_agent, tmp_path, backend):
    import base64
    import io
    import random
    Image = pytest.importorskip('PIL.Image')
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.executor.tools import FunctionTool
    from cota.runtime.pi_runtime import PiAgentRuntime
    from cota.store import MemoryStore, SQLStore
    from tests.test_pi_runtime import call

    image = Image.frombytes('RGB', (768, 768), random.Random(7).randbytes(768 * 768 * 3))
    output = io.BytesIO()
    image.save(output, format='PNG')
    encoded = base64.b64encode(output.getvalue()).decode()
    mock_agent._llm_mock.context_window = 1000000
    mock_agent.dialogue['compaction'] = {'max_request_bytes': 5 * 1024 * 1024}
    mock_agent.get_tool_registry().register(FunctionTool('picture', 'Read the current page image',
        {'type': 'object', 'properties': {}},
        lambda: {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': encoded}]}))
    dialogue = iter([{'tool_calls': [call('picture', {}, f'image{i}')]} for i in range(3)] + [{'content': 'Images inspected.'}])
    seen, summaries = [], []

    async def model(**kwargs):
        if 'context summarization assistant' in kwargs['messages'][0]['content']:
            summaries.append(kwargs)
            assert encoded not in str(kwargs)
            return {'content': 'Make a book. The earlier page was inspected; continue from the latest images.'}
        seen.append(kwargs)
        return next(dialogue)

    mock_agent._llm_mock.generate_chat.side_effect = model
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'byte-budget.db'))
    dst = DST('bytes', mock_agent)
    dst.append_event(UserUtterEvent('Make a book.'))
    try:
        await PiAgentRuntime(mock_agent, dst, 'bytes', checkpoint=store.save, store=store).run()
        assert dst.execution['status'] == 'completed'
        assert not summaries and len(seen) == 4
        assert sum(e.type == 'tool_result' for e in dst.events) == 3
        assert not any(e.type == 'context_compaction' for e in dst.events)
        assert encoded in str(seen[-1]['messages'])
        images = [b for m in seen[-1]['messages'] if isinstance(m.get('content'), list)
                  for b in m['content'] if b['type'] == 'image_url']
        assert len(images) == 1
        assert all(e.payload['content'][0]['data'] == encoded for e in dst.events if e.type == 'tool_result')
        assert len(str(seen[-1]['messages'])) < 5 * 1024 * 1024
        restored = await store.load('bytes', agent=mock_agent)
        replay = DST.from_events('bytes', dst.events, agent=mock_agent, run_metadata=dst.run_metadata)
        assert restored.state_dict() == replay.state_dict() == dst.state_dict()
    finally:
        if backend == 'sqlite':
            store.engine.dispose()

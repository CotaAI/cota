"""Native model observations preserve Cota's persistence and provenance contracts."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from cota.dst import DST
from cota.events import Event
from cota.runtime.pi_trace import PiTraceRecorder
from cota.store import MemoryStore


def message(text='hello'):
    return {'role': 'assistant', 'content': [{'type': 'text', 'text': text}],
            'stopReason': 'stop', 'timestamp': 1, 'model': 'test',
            'usage': {'input': 5, 'output': 2, 'cacheRead': 0, 'cacheWrite': 0, 'totalTokens': 7}}


@pytest.mark.asyncio
async def test_image_projection_usage_source_survives_replay_without_debug():
    from cota.runtime.pi_models import PiModelObserver
    dst, store = DST('projection', None), MemoryStore()
    dst.append_event(Event('run_started', {}, run_id='r'))
    trace = PiTraceRecorder(dst, store)
    observer = PiModelObserver(trace, AsyncMock())
    key = 'a' * 64
    call = await observer.begin({'purpose': 'dialogue', 'model': 'test',
                                 'contextBudget': {'image_projection': key}})
    await observer.complete({'request_id': call['request_id'], 'message': message(), 'duration_ms': 1})
    event = trace.observe_assistant(message())
    assert event.payload['llm']['image_projection'] == key
    restored = DST.from_events('projection', dst.events)
    assert restored.context_messages[-1]['cotaImageProjection'] == key
    assert await store.model_debug('projection', call['request_id']) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_commit', [False, True])
async def test_native_overflow_continues_only_after_durable_compaction(mock_agent, tmp_path, fail_commit):
    import json
    from aiohttp import web
    from cota.events import UserUtterEvent, BotUtterEvent
    from cota.executor.tools import FunctionTool
    from cota.llm import LLM
    from cota.runtime.pi_runtime import PiAgentRuntime
    bodies, effects = [], []
    dialogue = 0

    async def serve(request):
        nonlocal dialogue
        body = await request.json()
        bodies.append(body)
        summary = 'context summarization assistant' in body['messages'][0]['content']
        if not summary:
            dialogue += 1
        if not summary and dialogue == 2:
            return web.json_response({'error': {'message': 'maximum context length exceeded'}}, status=400)
        delta = {'role': 'assistant', 'content': 'Preserve the task and the committed effect.' if summary else 'done'}
        if not summary and dialogue == 1:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'effect-once', 'type': 'function',
                'function': {'name': 'effect', 'arguments': '{}'}}]}
        frames = [{'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                  {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if 'tool_calls' in delta else 'stop'}]}]
        return web.Response(text=''.join('data: ' + json.dumps(v) + '\n\n' for v in frames) + 'data: [DONE]\n\n',
                            content_type='text/event-stream')

    app = web.Application()
    app.router.add_post('/v1/chat/completions', serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    llm = LLM({'type': 'openai', 'key': 'local-only', 'model': 'test', 'context_window': 1000000,
               'apibase': f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1'})
    mock_agent.llm_instance = lambda name=None: llm
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'Save a result',
        {'type': 'object', 'properties': {}}, lambda: effects.append('saved') or {'saved': True}))
    mock_agent.dialogue['compaction'] = {'keep_recent_tokens': 10}
    dst, store = DST('overflow', mock_agent), MemoryStore()
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(UserUtterEvent('older facts ' * 2000))
    dst.append_event(BotUtterEvent('Earlier work saved.'))
    dst.append_event(UserUtterEvent('continue'))

    async def save(tracker):
        if fail_commit and any(e.type == 'context_compaction' for e in tracker.events):
            raise OSError('compaction storage failed')
        await store.save(tracker)

    try:
        runtime = PiAgentRuntime(mock_agent, dst, 'overflow', max_iterations=5, checkpoint=save, store=store)
        if fail_commit:
            with pytest.raises(OSError, match='compaction storage failed'):
                await runtime.run()
            assert dialogue == 2
            assert not any(e['type'] == 'context_compaction' for e in await store.events('overflow'))
        else:
            await runtime.run()
            assert dst.execution['status'] == 'completed' and dialogue == 3
            event = next(e for e in dst.events if e.type == 'context_compaction')
            assert event.payload['reason'] == 'overflow' and event.payload['tokens_before'] > 0
            restored = await store.load('overflow', mock_agent)
            assert DST.from_events('overflow', dst.events, mock_agent).state_dict() == restored.state_dict() == dst.state_dict()
            assert 'maximum context' not in str(restored.context_messages)
            assert len([e for e in dst.events if e.type == 'tool_started' and e.tool == 'effect']) == 1
        assert effects == ['saved']
        records = [await store.model_debug('overflow', row['request_id']) for row in await store.model_debug_headers('overflow')]
        assert any(r.get('error_type') == 'ContextOverflowError' for r in records)
    finally:
        await llm.close()
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_native_response_is_staged_and_debug_request_is_optional(tmp_path, debug):
    from cota.runtime.pi_models import PiModelObserver
    store, dst = MemoryStore(), DST('s', None)
    if debug:
        store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    trace = PiTraceRecorder(dst, store)
    trace.policy = {'policies': [{'name': 'greeting'}]}
    checkpoint = AsyncMock(side_effect=lambda: store.save(dst))
    # AsyncMock does not await a coroutine returned by a lambda.
    async def save():
        await store.save(dst)
    observer = PiModelObserver(trace, save)
    began = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    assert began['debug'] is debug
    assert (await store.load('s')).execution['status'] == 'running'
    body = {'messages': [{'role': 'user', 'content': 'hello'}], 'stream': True}
    await observer.observe({'request_id': began['request_id'], 'kind': 'request', 'request': body})
    await observer.complete({'request_id': began['request_id'], 'message': message(), 'duration_ms': 50,
                             'transport': {'attempts': [{'number': 1, 'status': 'completed'}]}})
    event = trace.observe_assistant(message())
    await save()
    await trace.link_model_debug(event)
    assert event.payload['llm']['policy'] == trace.policy
    assert event.payload['llm']['usage']['totalTokens'] == 7
    assert [e.type for e in dst.events] == ['run_started', 'bot_utter']
    record = await store.model_debug('s', began['request_id'])
    if debug:
        assert record['request'] == body
        assert record['response']['content'] == 'hello'
        assert record['event_id'] == event.event_id
        assert record['transport']['attempts'][0]['number'] == 1
    else:
        assert record is None
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()
    checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_start_checkpoint_prevents_native_request():
    from cota.runtime.pi_models import PiModelObserver
    dst = DST('s', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    observer = PiModelObserver(PiTraceRecorder(dst), AsyncMock(side_effect=OSError('store failed')))
    with pytest.raises(OSError, match='store failed'):
        await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    assert not observer.active


@pytest.mark.asyncio
async def test_native_summary_and_failed_requests_do_not_create_assistant_facts(tmp_path, caplog):
    from cota.runtime.pi_models import PiModelObserver
    store, dst = MemoryStore(), DST('s', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    trace = PiTraceRecorder(dst, store)
    observer = PiModelObserver(trace, AsyncMock())
    request = await observer.begin({'purpose': 'compaction', 'model': 'test'})
    await observer.complete({'request_id': request['request_id'], 'message': message('summary'), 'duration_ms': 10})
    assert trace._pending_model is None
    request = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    await observer.fail({'request_id': request['request_id'], 'error_type': 'TimeoutError',
                         'error': 'PRIVATE_PROVIDER_BODY', 'duration_ms': 20})
    assert trace._pending_model is None and not observer.active
    assert 'PRIVATE_PROVIDER_BODY' not in caplog.text
    record = await store.model_debug('s', request['request_id'])
    assert record['status'] == 'failed' and record['error_type'] == 'TimeoutError'
    assert len(dst.events) == 1
    with pytest.raises(ValueError, match='Unknown|completed'):
        await observer.complete({'request_id': request['request_id'], 'message': message(), 'duration_ms': 20})


@pytest.mark.asyncio
async def test_cancellation_finishes_outstanding_debug_request(tmp_path):
    from cota.runtime.pi_models import PiModelObserver
    store, dst = MemoryStore(), DST('s', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    observer = PiModelObserver(PiTraceRecorder(dst, store), AsyncMock())
    request = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    await observer.interrupt(asyncio.CancelledError())
    record = await store.model_debug('s', request['request_id'])
    assert record['status'] == 'interrupted' and not observer.active


def test_public_native_content_does_not_expose_thinking():
    from cota.runtime.pi_models import public_message
    native = message()
    native['content'].insert(0, {'type': 'thinking', 'thinking': 'private reasoning', 'thinkingSignature': 'sig'})
    native['content'][1]['textSignature'] = 'signature'
    original = deepcopy(native)
    assert public_message(native)['content'] == [{'type': 'text', 'text': 'hello'}]
    assert native == original


@pytest.mark.asyncio
async def test_openai_endpoint_exports_native_transport_but_custom_adapters_do_not():
    from cota.llm.llm import LLM
    config = {'key': 'private-key', 'apibase': 'https://example.invalid/v1', 'model': 'test',
              'thinking': 'disabled', 'vision': True, 'timeout_seconds': 12, 'max_retries': 1}
    llm = LLM(config)
    rag = LLM({**config, 'type': 'openai-rag', 'knowledge_id': 'kb'})
    try:
        assert llm.pi_provider() == {'apiKey': 'private-key', 'baseUrl': 'https://example.invalid/v1/',
                                     'model': 'test', 'thinking': 'disabled', 'vision': True,
                                     'timeoutSeconds': 12, 'maxRetries': 1}
        assert rag.pi_provider() is None
    finally:
        await llm.close()
        await rag.close()


@pytest.mark.asyncio
async def test_native_prepare_uses_durable_projection_without_returning_history(mock_agent):
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    dst.append_event(Event('run_started', {}, run_id='r'))
    runtime = PiAgentRuntime(mock_agent, dst, 's')
    runtime._system_prompt = 'You are helpful.'
    prepared = await runtime._prepare({'native': True, 'skillPrompt': 'Skills', 'toolPrompt': '',
                                       'nativeTools': [], 'extensionTools': []})
    assert 'messages' not in prepared
    assert prepared['systemPrompt'] == 'You are helpful.Skills'
    assert prepared['imageResources'] == []


@pytest.mark.asyncio
async def test_real_node_greeting_streams_before_completion_and_restores_history(mock_agent):
    import json
    from cota.events import UserUtterEvent
    from cota.llm.llm import LLM
    from cota.runtime.pi_runtime import PiAgentRuntime
    requests, streams, delivered, tasks = [], [], [], set()
    first_delta = asyncio.Event()

    async def serve(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
            except asyncio.IncompleteReadError:
                return
            length = next(int(line.split(b':', 1)[1]) for line in header.split(b'\r\n')
                          if line.lower().startswith(b'content-length:'))
            requests.append(json.loads(await reader.readexactly(length)))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n')
            def emit(delta, finish=None):
                chunk = {'id': 'response', 'object': 'chat.completion.chunk', 'model': 'test',
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                writer.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            emit({'role': 'assistant', 'content': 'Hello'})
            await writer.drain()
            await asyncio.wait_for(first_delta.wait(), 5)
            emit({'content': ' there'})
            emit({}, 'stop')
            writer.write(b'data: [DONE]\n\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    llm = LLM({'key': 'local-test', 'apibase': f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
               'model': 'test', 'timeout_seconds': 10, 'thinking': 'disabled'})
    llm.generate_chat = AsyncMock(side_effect=AssertionError('Main dialogue must run in Node'))
    mock_agent.llm_instance = lambda name=None: llm
    store, dst = MemoryStore(), DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    async def stream(item):
        streams.append(item)
        if item['phase'] == 'delta':
            assert not delivered
            first_delta.set()
    async def reply(item):
        assert await store.event_by_id('s', item['event_id'])
        delivered.append(item)
    try:
        runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save, store=store)
        runtime.set_stream_callback(stream)
        runtime.set_channel_callback(reply)
        await runtime.run()
        assert ''.join(i.get('text', '') for i in streams) == 'Hello there'
        assert [i['text'] for i in delivered] == ['Hello there']
        assert delivered[0]['request_id'] == streams[0]['request_id']
        assert dst.execution['status'] == 'completed'
        assert 'thinking' in requests[0] and requests[0]['stream'] is True
        restored = await store.load('s', mock_agent)
        restored.append_event(UserUtterEvent('again'))
        await PiAgentRuntime(mock_agent, restored, 's', checkpoint=store.save, store=store).run()
        assert [m['content'] for m in requests[1]['messages'] if m['role'] == 'assistant'] == ['Hello there']
        llm.generate_chat.assert_not_awaited()
        assert DST.from_events('s', restored.events, mock_agent).state_dict() == restored.state_dict()
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*tasks, return_exceptions=True)
        await llm.close()


@pytest.mark.asyncio
async def test_native_reasoning_continuation_survives_store_without_being_public(tmp_path):
    from cota.runtime.pi_models import PiModelObserver, public_message
    store, dst = MemoryStore(), DST('s', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    trace = PiTraceRecorder(dst, store)
    observer = PiModelObserver(trace, AsyncMock())
    native = message('visible')
    native.update(api='openai-completions', provider='cota')
    native['content'].insert(0, {'type': 'thinking', 'thinking': 'private continuation',
                                  'thinkingSignature': 'reasoning_content'})
    request = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    await observer.complete({'request_id': request['request_id'], 'message': native, 'duration_ms': 10})
    event = trace.observe_assistant(public_message(native))
    assert event.text == 'visible'
    assert event.payload['llm']['continuation']['content'] == native['content']
    await store.save(dst)
    restored = await store.load('s')
    assert restored.context_messages[-1]['content'] == native['content']
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()
    assert 'continuation' not in message()


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_commit', [False, True])
async def test_native_tool_batch_commits_commentary_before_effect_and_refreshes_policy(mock_agent, tmp_path, fail_commit):
    import json
    from cota.events import UserUtterEvent
    from cota.executor.tools.base import FunctionTool
    from cota.llm.llm import LLM
    from cota.runtime.pi_runtime import PiAgentRuntime
    store, dst = MemoryStore(), DST('s', mock_agent)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(UserUtterEvent('look up'))
    effects, requests, delivered, streams, tasks = [], [], [], [], set()

    async def lookup(city: str):
        saved = await store.events('s')
        assert any(e['type'] == 'tool_started' for e in saved)
        assert any(e['type'] == 'bot_utter' and e['payload']['text'] == 'Checking now.' for e in saved)
        assert delivered == ['Checking now.']
        effects.append(city)
        return {'weather': 'sunny'}
    mock_agent._tool_registry.register(FunctionTool(name='lookup', description='lookup', parameters={'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}, handler=lookup))
    original_guidance = mock_agent.policy.guidance
    async def guidance(context, services):
        result = await original_guidance(context, services)
        result['text'] = 'results_seen=' + str(sum(o['role'] == 'tool' for o in context.observations))
        return result
    mock_agent.policy.guidance = guidance

    async def serve(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
            except asyncio.IncompleteReadError:
                return
            length = next(int(line.split(b':', 1)[1]) for line in header.split(b'\r\n')
                          if line.lower().startswith(b'content-length:'))
            requests.append(json.loads(await reader.readexactly(length)))
            first = len(requests) == 1
            delta = {'role': 'assistant', 'content': 'Checking now.' if first else 'It is sunny.'}
            if first:
                delta['tool_calls'] = [{'index': 0, 'id': 'lookup-1', 'type': 'function',
                                         'function': {'name': 'lookup', 'arguments': '{"city":"A"}'}}]
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n')
            for data, reason in ((delta, None), ({}, 'tool_calls' if first else 'stop')):
                chunk = {'id': 'native', 'model': 'test', 'object': 'chat.completion.chunk',
                         'choices': [{'index': 0, 'delta': data, 'finish_reason': reason}]}
                writer.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            writer.write(b'data: [DONE]\n\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    llm = LLM({'key': 'test-private-key', 'apibase': f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
               'model': 'test', 'timeout_seconds': 10})
    mock_agent.llm_instance = lambda name=None: llm
    async def checkpoint(tracker):
        if fail_commit and any(e.type == 'tool_started' for e in tracker.events):
            raise OSError('native checkpoint failed')
        await store.save(tracker)
    async def reply(item):
        delivered.append(item['text'])
    async def preview(item):
        streams.append(item)
    try:
        runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=checkpoint, store=store)
        runtime.set_channel_callback(reply)
        runtime.set_stream_callback(preview)
        if fail_commit:
            with pytest.raises(OSError, match='native checkpoint failed'):
                await runtime.run()
            assert not effects and not delivered and len(requests) == 1
            assert streams[-1]['phase'] == 'error'
        else:
            await runtime.run()
            assert effects == ['A'] and delivered == ['Checking now.', 'It is sunny.']
            assert 'lookup' in [tool['function']['name'] for tool in requests[0].get('tools', [])]
            assert 'lookup' in [tool['function']['name'] for tool in requests[1].get('tools', [])]
            assert requests[0]['messages'][0] == requests[1]['messages'][0]
            assert 'results_seen=0' in str(requests[0]['messages'][-1]['content'])
            assert 'results_seen=1' in str(requests[1]['messages'][-1]['content'])
            assert [m['role'] for m in requests[1]['messages']] == ['system', 'user', 'assistant', 'tool', 'user']
            assert requests[1]['messages'][2]['content'] == 'Checking now.'
            assert DST.from_events('s', dst.events, mock_agent).state_dict() == dst.state_dict()
            records = await store.model_debug_headers('s')
            assert len(records) == 2
            debug = await store.model_debug('s', next(e.payload['llm']['request_id'] for e in dst.events if e.type == 'tool_started'))
            assert debug['request'] == requests[0] and debug['request_stage'] == 'provider'
            assert 'test-private-key' not in json.dumps(debug)
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*tasks, return_exceptions=True)
        await llm.close()


@pytest.mark.asyncio
async def test_custom_prepare_projects_attachments_without_reading_pixels(mock_agent, tmp_path):
    from unittest.mock import Mock
    from cota.files import FileStorage
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = FileStorage(tmp_path)
    item = mock_agent.files.put('images', 'u', 'one.png', b'\x89PNG\r\n\x1a\nimage')
    mock_agent.files.read = Mock(side_effect=AssertionError('prepare must not read image bytes'))
    dst = DST('images', mock_agent)
    dst.append_event(UserUtterEvent('inspect', attachments=[item]))
    dst.append_event(Event('run_started', {}, run_id='image-run'))
    runtime = PiAgentRuntime(mock_agent, dst, 'images')
    prepared = await runtime._prepare({'nativeTools': [], 'extensionTools': []})
    assert prepared['imageResources'][0]['id'] == item['id']
    assert prepared['messages'][1]['cotaAttachmentsHydrated'] is True
    mock_agent.files.read.assert_not_called()


@pytest.mark.asyncio
async def test_custom_transport_passes_request_only_images_without_rehydration(mock_agent):
    from cota.runtime.pi_runtime import PiAgentRuntime
    runtime = PiAgentRuntime(mock_agent, DST('images', mock_agent), 'images')
    projected = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Image pixels omitted: re-read to inspect.'}],
                  'cotaAttachments': [{'id': 'image', 'mime_type': 'image/png', 'size': 5}],
                  'cotaAttachmentsHydrated': True}]
    await runtime._handle_request('model', {'messages': projected, 'systemPrompt': 'test', 'tools': []})
    sent = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert sent[1]['content'] == projected[0]['content']


@pytest.mark.asyncio
async def test_custom_adapter_restart_keeps_new_attachment_pixels_and_old_text_observations(mock_agent, tmp_path):
    import base64
    import json
    from cota.events import UserUtterEvent
    from cota.files import FileStorage
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = FileStorage(tmp_path / 'files')
    mock_agent._llm_mock.supports_images = True
    mock_agent.dialogue['compaction'] = {'max_images': 1}
    first = mock_agent.files.put('image-session', 'user', 'first.png', b'\x89PNG\r\n\x1a\nfirst')
    second = mock_agent.files.put('image-session', 'user', 'second.png', b'\x89PNG\r\n\x1a\nsecond')
    store, dst = MemoryStore(), DST('image-session', mock_agent)
    dst.append_event(UserUtterEvent('inspect first', attachments=[first]))
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'The border is blue.'}
    await PiAgentRuntime(mock_agent, dst, 'image-session', checkpoint=store.save).run()
    restored = await store.load('image-session', agent=mock_agent)
    restored.append_event(UserUtterEvent('compare using your observations', attachments=[second]))
    await PiAgentRuntime(mock_agent, restored, 'image-session', checkpoint=store.save).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    images = [block for message in messages if isinstance(message.get('content'), list)
              for block in message['content'] if block.get('type') == 'image_url']
    assert len(images) == 1
    assert images[0]['image_url']['url'].endswith(base64.b64encode(b'\x89PNG\r\n\x1a\nsecond').decode())
    assert 'The border is blue.' in json.dumps(messages)
    assert first['id'] in json.dumps(messages) and 'sha256:' in json.dumps(messages)
    assert 'Image pixels omitted' not in json.dumps(restored.as_dict())
    assert not any(event.type == 'context_compaction' for event in restored.events)


@pytest.mark.asyncio
async def test_attachment_resource_rpc_checks_current_integrity(mock_agent, tmp_path):
    from cota.events import UserUtterEvent
    from cota.files import FileStorage
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = FileStorage(tmp_path / 'files')
    current = mock_agent.files.put('images', 'u', 'current.png', b'\x89PNG\r\n\x1a\nimage')
    path = mock_agent.files.resolve('images', current['id'])
    dst = DST('images', mock_agent)
    dst.append_event(UserUtterEvent('inspect', attachments=[current]))
    runtime = PiAgentRuntime(mock_agent, dst, 'images')
    await runtime._initial_context()
    assert (await runtime._handle_request('image_resource', {'id': current['id']}))['type'] == 'image'
    path.write_bytes(b'bad image')
    assert 'error' in await runtime._handle_request('image_resource', {'id': current['id']})


@pytest.mark.asyncio
async def test_debug_cache_usage_and_static_prefix_changes_are_explicit(tmp_path):
    from cota.runtime.pi_models import PiModelObserver
    store, dst = MemoryStore(), DST('cache', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='cache-run'))
    trace = PiTraceRecorder(dst, store)
    async def checkpoint(): await store.save(dst)
    observer = PiModelObserver(trace, checkpoint)
    records = []
    for system in ['stable', 'stable', 'changed']:
        began = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
        await observer.observe({'request_id': began['request_id'], 'kind': 'request', 'request': {
            'model': 'test', 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': 'current guidance'}], 'tools': []}})
        response = message()
        response['usage'] = {'input': 20, 'cacheRead': 80, 'cacheWrite': 0, 'output': 2, 'totalTokens': 102}
        await observer.complete({'request_id': began['request_id'], 'message': response, 'duration_ms': 5})
        records.append(await store.model_debug('cache', began['request_id']))
    assert records[1]['cache']['changes'] == []
    assert records[2]['cache']['changes'] == ['system']
    assert records[1]['usage']['cached_tokens'] == 80
    assert records[1]['usage']['uncached_tokens'] == 20
    assert records[1]['usage']['cache_hit_ratio'] == .8

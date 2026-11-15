"""Retrieval metadata survives Pi execution, durable replay and later requests."""
import json

from aiohttp import web
import pytest

from cota.dst import DST
from cota.events import UserUtterEvent
from cota.knowledge import KnowledgeIndex, KnowledgeTool
from cota.llm import LLM
from cota.policy import PolicyIndex, PolicyTool
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore, SQLStore


@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
@pytest.mark.parametrize('debug', [False, True])
async def test_native_retrieval_batch_preserves_origin_and_projects_old_results(
        mock_agent, tmp_path, backend, debug):
    knowledge = tmp_path / 'knowledge'
    knowledge.mkdir()
    (knowledge / 'KNOWLEDGE.md').write_text(
        '---\nname: support\ndescription: refunds\nrerank: true\n---\nrefund.md', encoding='utf-8')
    (knowledge / 'refund.md').write_text(
        '# 退款\n未找到订单时，先核对订单号。\n\n---\n\n退款期限是七天。', encoding='utf-8')
    policy = tmp_path / 'policy'
    policy.mkdir()
    (policy / 'POLICY.md').write_text(
        '---\nname: support\ndescription: refunds\n---\n'
        '## refund-query\n- User: 退款\n- Bot:\n  - Reply: 请提供订单号。\n'
        '## refund-missing\n- User: 退款查询\n- Bot:\n'
        '  - Result: 未找到订单。\n  - Thought: 请用户核对订单号。\n', encoding='utf-8')
    requests, dialogue = [], []

    async def serve(request):
        body = await request.json()
        requests.append(body)
        if not body.get('stream'):
            return web.json_response({'id': 'rank', 'object': 'chat.completion', 'created': 1,
                'model': 'test', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '0'},
                                            'finish_reason': 'stop'}]})
        dialogue.append(body)
        delta, finish = {'role': 'assistant', 'content': '已保存查询结果。'}, 'stop'
        if len(dialogue) == 1:
            delta = {'role': 'assistant', 'content': '我先查阅退款资料。', 'tool_calls': [
                {'index': index, 'id': name, 'type': 'function',
                 'function': {'name': name, 'arguments': json.dumps(args)}}
                for index, (name, args) in enumerate([
                    ('search_knowledge', {'query': '退款'}), ('policy_guidance', {'scenario': '退款'})])]}
            finish = 'tool_calls'
        frames = [{'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                  {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}]
        return web.Response(text=''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames)
                            + 'data: [DONE]\n\n', content_type='text/event-stream')

    app = web.Application()
    app.router.add_post('/v1/chat/completions', serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    llm = LLM({'type': 'openai', 'key': 'local-only', 'model': 'test', 'context_window': 100000,
               'apibase': f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1'})
    mock_agent.llm_instance = lambda name=None: llm
    registry = mock_agent.get_tool_registry()
    registry.register(KnowledgeTool(KnowledgeIndex.build(knowledge), mock_agent))
    registry.register(PolicyTool(PolicyIndex.build(policy)))
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'sessions.db'))
    if debug:
        store.enable_debug_log(tmp_path / 'debug.log')
    dst = DST('retrieval', mock_agent)
    try:
        dst.append_event(UserUtterEvent('退款如何办理？'))
        await PiAgentRuntime(mock_agent, dst, dst.session_id, max_iterations=5,
                             checkpoint=store.save, store=store).run()
        first_run = dst.execution['run_id']
        assert dst.execution['status'] == 'completed'
        starts = [event for event in dst.events if event.type == 'tool_started']
        assert [event.tool for event in starts] == ['search_knowledge', 'policy_guidance']
        assert starts[1].payload['llm_event_id'] == starts[0].event_id
        results = [event for event in dst.events if event.type == 'tool_result']
        assert [event.payload['result']['details']['hits'] for event in results] == [1, 2]
        assert '1条结果' in results[0].payload['context']['summary']
        assert '2条结果' in results[1].payload['context']['summary']
        assert '七天' in str(results[0].payload)
        assert '七天' in str(dialogue[1]['messages'])
        assert len([body for body in requests if not body.get('stream')]) == 1

        # Restore through Store before continuing: events/snapshots retain the
        # complete evidence, while the later native request gets summaries.
        restored = await store.load(dst.session_id, mock_agent)
        assert restored.state_dict() == DST.from_events(dst.session_id, dst.events, mock_agent).state_dict()
        restored.append_event(UserUtterEvent('继续'))
        await PiAgentRuntime(mock_agent, restored, restored.session_id, max_iterations=5,
                             checkpoint=store.save, store=store).run()
        assert restored.execution['status'] == 'completed'
        assert len(dialogue) == 3
        tool_messages = [message for message in dialogue[-1]['messages'] if message['role'] == 'tool']
        assert len(tool_messages) == 2
        assert '1条结果' in str(tool_messages[0]) and '2条结果' in str(tool_messages[1])
        assert '七天' not in str(tool_messages)
        assert any('七天' in str(event.payload) for event in (await store.load(dst.session_id)).events)
        if debug:
            headers = await store.model_debug_headers(dst.session_id)
            assert sum(row['purpose'] == 'knowledge' for row in headers) == 1
            origin = await store.model_debug(dst.session_id, starts[0].payload['llm']['request_id'])
            assert origin['purpose'] == 'dialogue' and origin['run_id'] == first_run
        else:
            assert await store.model_debug_headers(dst.session_id) == []
    finally:
        await llm.close()
        await runner.cleanup()
        if backend == 'sqlite':
            store.engine.dispose()

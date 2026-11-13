"""Python coordinates committed summaries and actual backend attachment limits."""
from unittest.mock import AsyncMock
import json

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent
from cota.files import FileStorage
from cota.runtime.pi_runtime import PiAgentRuntime


@pytest.mark.asyncio
async def test_budget_summary_is_not_replaced_by_generic_limit_message(mock_agent):
    dst=DST('wrapup',mock_agent);dst.append_event(UserUtterEvent('Make a book'))
    runtime=PiAgentRuntime(mock_agent,dst,'wrapup',max_iterations=100)
    async def bridge(options,handler):
        dst.append_event(BotUtterEvent('PDF已保存，附件尚未发出：需要先缩小文件。'))
        return {'status':'limited','hasFinalReply':True}
    runtime._bridge.run=AsyncMock(side_effect=bridge)
    await runtime.run()
    replies=[e.text for e in dst.events if e.type=='bot_utter']
    assert replies==['PDF已保存，附件尚未发出：需要先缩小文件。']
    assert dst.execution['status']=='limited'


@pytest.mark.asyncio
async def test_actual_file_backend_limits_reach_node(mock_agent,tmp_path,monkeypatch):
    import cota.files as files
    monkeypatch.setattr(files,'MAX_FILE_BYTES',123456)
    mock_agent.files=FileStorage(tmp_path/'files')
    dst=DST('limits',mock_agent);dst.append_event(UserUtterEvent('Send files'))
    runtime=PiAgentRuntime(mock_agent,dst,'limits')
    runtime._bridge.run=AsyncMock(return_value={'status':'completed'})
    await runtime.run()
    assert runtime._bridge.run.call_args.args[0]['fileLimits']=={'max_file_bytes':123456,'max_attachments':8}


@pytest.mark.asyncio
async def test_send_files_preserves_actionable_size_error_details(mock_agent,tmp_path):
    mock_agent.files=FileStorage(tmp_path/'files')
    with (tmp_path/'book.pdf').open('wb') as stream:stream.truncate(20*1024*1024+85085)
    dst=DST('delivery',mock_agent);dst.append_event(UserUtterEvent('Send PDF'))
    dst.append_event(Event('run_started',{},run_id='r'))
    args={'paths':['book.pdf']}
    dst.append_event(Event('tool_started',{'tool':'send_files','tool_call_id':'send','arguments':args}))
    runtime=PiAgentRuntime(mock_agent,dst,'delivery')
    runtime._files_allowed=lambda:True
    from cota.executor.environment import ExecutionEnvironment
    runtime._environment=ExecutionEnvironment(type='machine',workspace=str(tmp_path))
    response=await runtime._handle_request('send_files',{'toolCallId':'send','args':args})
    assert response['isError'] is True
    assert response['details']['reason']=='file_too_large'
    assert response['details']['actual_bytes']==20*1024*1024+85085
    text=json.loads(response['content'][0]['text'])
    assert text['file']=='book.pdf' and text['max_file_bytes']==20*1024*1024
    assert not any(e.type=='bot_utter' for e in dst.events)


@pytest.mark.asyncio
async def test_custom_text_only_closure_omits_empty_tool_parameters(mock_agent):
    runtime=PiAgentRuntime(mock_agent,DST('text-only',mock_agent),'text-only')
    await runtime._call_llm([{'role':'user','content':'Summarize actual progress.'}],[])
    parameters=mock_agent._llm_mock.generate_chat.call_args.kwargs
    assert 'tools' not in parameters and 'tool_choice' not in parameters


@pytest.mark.asyncio
async def test_real_pi_wrapup_commits_useful_reply_within_original_budget(mock_agent):
    from cota.executor.tools.base import FunctionTool
    from cota.store import MemoryStore
    calls=[]
    def work():
        calls.append(len(calls)+1)
        return {'saved_result':calls[-1]}
    mock_agent.get_tool_registry().register(FunctionTool('work','Save one result',
        {'type':'object','properties':{}},work))
    model_requests=[]
    async def respond(**kwargs):
        model_requests.append(kwargs)
        if kwargs.get('tool_choice') == 'none':
            return {'content':f'已完成 {len(calls)} 次处理，尚未发送任何附件。'}
        return {'tool_calls':[{'id':f'work-{len(calls)+1}','type':'function',
            'function':{'name':'work','arguments':'{}'}}]}
    mock_agent._llm_mock.generate_chat.side_effect=respond
    store=MemoryStore()
    dst=DST('real-wrap',mock_agent);dst.append_event(UserUtterEvent('Process the work'))
    runtime=PiAgentRuntime(mock_agent,dst,'real-wrap',max_iterations=10,checkpoint=store.save,store=store)
    await runtime.run()
    assert len(calls)==8 and len(model_requests)==9
    assert model_requests[-1]['tools'] == model_requests[0]['tools']
    assert model_requests[-1]['tool_choice'] == 'none'
    assert '<execution_budget phase="wrap_up">' in str(model_requests[-1]['messages'][-1]['content'])
    assert all(r['messages'][0] == model_requests[0]['messages'][0] for r in model_requests)
    assert [e.text for e in dst.events if e.type=='bot_utter']==['已完成 8 次处理，尚未发送任何附件。']
    assert dst.execution['status']=='limited'
    assert (await store.load('real-wrap',mock_agent)).state_dict()==dst.state_dict()

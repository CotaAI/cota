"""Private Feishu events through real Application/Runner/Processor/Pi/Store."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from cota.application import Application
from cota.channels.platforms.feishu import FeishuChannel
from cota.executor.user_memory import MemoryUserMemory
from tests.channels.test_feishu import event


@pytest.mark.asyncio
async def test_private_users_fifo_isolation_duplicate_and_committed_delivery(mock_agent):
    mock_agent.cleanup=AsyncMock()
    mock_agent.user_memory=MemoryUserMemory()
    await mock_agent.user_memory.aset('feishu:cli_test:t1:ou_alice','city','Beijing')
    await mock_agent.user_memory.aset('feishu:cli_test:t1:ou_bob','city','Shanghai')
    entered,release,bob_sent,all_sent=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    observed={}; calls=[]; sent=[]
    async def model(**kwargs):
        users=[m['content'] for m in kwargs['messages'] if m['role']=='user']
        text=users[-1];calls.append(text); observed[text]=users
        if text=='alice-one':
            entered.set();await release.wait()
        return {'content':'reply:'+text}
    mock_agent._llm_mock.generate_chat.side_effect=model
    app=Application(mock_agent,concurrency=2)
    async def http(request):
        if '/auth/' in str(request.url):
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        payload=json.loads(request.content); text=json.loads(payload['content'])['text']
        sid='feishu:cli_test:t1:p2p:'+payload['receive_id']
        history=await app.history(sid)
        assert any(m['text']==text and m['role']=='bot' for m in history['messages'])
        sent.append((payload['receive_id'],text))
        if text=='reply:bob-one': bob_sent.set()
        if len(sent)==3: all_sent.set()
        return httpx.Response(200,json={'code':0})
    async with app:
        # Network startup is verified separately with the SDK worker test.
        ch=FeishuChannel({'app_id':'cli_test','app_secret':'secret','allow_from':['*']},app.runner.message_bus)
        ch._http_client=httpx.AsyncClient(transport=httpx.MockTransport(http))
        app.runner.channel_manager.channels['feishu']=ch
        async def receive(user,chat,mid,text):
            data=event(user,chat,mid)
            data['event']['message']['content']=json.dumps({'text':text})
            assert await ch._on_event(data)
        try:
            await receive('ou_alice','oc_alice','a1','alice-one')
            await asyncio.wait_for(entered.wait(),10)
            await receive('ou_alice','oc_alice','a1','alice-one')
            await receive('ou_alice','oc_alice','a2','alice-two')
            await receive('ou_bob','oc_bob','b1','bob-one')
            await asyncio.wait_for(bob_sent.wait(),10)
            assert not all_sent.is_set()
            release.set()
            await asyncio.wait_for(all_sent.wait(),10)
            assert calls.count('alice-one')==1
            assert observed['bob-one']==['bob-one']
            assert observed['alice-two']==['alice-one','alice-two']
            assert [text for chat,text in sent if chat=='oc_alice']==['reply:alice-one','reply:alice-two']
            alice=await app.store.load('feishu:cli_test:t1:p2p:oc_alice')
            bob=await app.store.load('feishu:cli_test:t1:p2p:oc_bob')
            assert alice.user_context['city']=='Beijing'
            assert bob.user_context['city']=='Shanghai'
            assert (await app.receipt(alice.session_id,'a1'))['status']=='completed'
        finally:
            release.set()

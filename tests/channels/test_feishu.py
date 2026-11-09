"""Feishu private text contract against official event shapes and HTTP replies."""
import asyncio
import json

import httpx
import pytest

from cota.channels.events import OutboundMessage
from cota.channels.platforms.feishu import FeishuChannel
from cota.channels.queue import MessageBus


def event(user='ou_alice', chat='oc_alice', message='om_1', tenant='t1'):
    return {'schema':'2.0', 'header':{'event_type':'im.message.receive_v1', 'app_id':'cli_test',
            'tenant_key':tenant, 'event_id':'ev1'}, 'event':{
        'sender':{'sender_type':'user','sender_id':{'open_id':user},'tenant_key':tenant},
        'message':{'message_id':message,'chat_id':chat,'chat_type':'p2p',
                   'message_type':'text','content':json.dumps({'text':'hello'})}}}


def channel(**config):
    return FeishuChannel({'app_id':'cli_test','app_secret':'secret','allow_from':['*'],**config}, MessageBus())


@pytest.mark.asyncio
async def test_official_private_event_maps_scoped_identity_and_raw_reply_route():
    ch=channel()
    assert await ch._on_event(event()) is True
    message=await ch.bus.consume_inbound()
    assert message.channel=='feishu'
    assert message.sender_id=='feishu:cli_test:t1:ou_alice'
    assert message.session_key=='feishu:cli_test:t1:p2p:oc_alice'
    assert message.chat_id=='oc_alice'
    assert message.message_id=='om_1'
    assert message.content=='hello'
    await ch._on_event(event(tenant='t2'))
    other=await ch.bus.consume_inbound()
    assert other.sender_id!=message.sender_id and other.session_key!=message.session_key


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'chat_type':'group'},{'message_type':'image'}, {'message_id':None}])
async def test_group_media_and_missing_source_id_do_not_invoke_bot(change):
    ch=channel(); data=event();data['event']['message'].update(change)
    assert await ch._on_event(data) is False
    assert ch.bus.inbound_size==0


@pytest.mark.asyncio
async def test_robot_foreign_app_and_disallowed_user_are_ignored():
    ch=channel(allow_from=['ou_allowed'])
    assert await ch._on_event(event()) is False
    data=event(user='ou_allowed'); data['event']['sender']['sender_type']='app'
    assert await ch._on_event(data) is False
    data=event(user='ou_allowed');data['header']['app_id']='foreign'
    assert await ch._on_event(data) is False
    assert ch.bus.inbound_size==0


@pytest.mark.asyncio
async def test_send_uses_chat_id_type_and_stable_event_uuid_and_retries():
    calls=[];attempt=0
    async def handle(request):
        nonlocal attempt
        if '/auth/' in str(request.url):
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        attempt+=1; calls.append(request)
        if attempt==1:
            return httpx.Response(503,json={'code':1})
        return httpx.Response(200,json={'code':0,'data':{'message_id':'sent'}})
    ch=channel();ch._http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    msg=OutboundMessage('feishu','oc_alice','answer',event_id='reply',session_id='s',sequence=4)
    try:
        await ch.send(msg)
        assert len(calls)==2
        assert calls[0].url.params['receive_id_type']=='chat_id'
        payload=json.loads(calls[0].content)
        assert payload['receive_id']=='oc_alice'
        assert json.loads(payload['content'])=={'text':'answer'}
        assert payload['uuid']==json.loads(calls[1].content)['uuid']
        await ch.send(msg)
        assert payload['uuid']==json.loads(calls[-1].content)['uuid']
    finally:
        await ch._http_client.aclose()


@pytest.mark.asyncio
async def test_http_200_api_failure_is_not_silently_accepted():
    async def handle(request):
        if '/auth/' in str(request.url):
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        return httpx.Response(200,json={'code':230001,'msg':'sensitive payload must not be exposed'})
    ch=channel();ch._http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(RuntimeError,match='230001') as error:
            await ch.send(OutboundMessage('feishu','oc','hi',event_id='e',session_id='s'))
        assert 'sensitive' not in str(error.value)
    finally:
        await ch._http_client.aclose()


def test_real_sdk_deserializes_supported_event_shape():
    lark=pytest.importorskip('lark_oapi')
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    parsed=lark.JSON.unmarshal(json.dumps(event()), P2ImMessageReceiveV1)
    assert parsed.event.message.chat_type=='p2p'
    assert parsed.event.sender.sender_id.open_id=='ou_alice'


@pytest.mark.asyncio
async def test_official_sdk_worker_process_readiness_admission_and_stop(monkeypatch):
    pytest.importorskip('lark_oapi')
    import sys
    import cota.channels.platforms.feishu as module
    create_process=asyncio.create_subprocess_exec
    # Only network connection is replaced. The real SDK model/dispatcher,
    # worker entry point, pipes, acknowledgment and process stop all run.
    script='''import asyncio, json, time
import lark_oapi as lark
from cota.channels.platforms.feishu_worker import main
async def connected(self): pass
lark.ws.Client._connect=connected
def start(self):
    import lark_oapi.ws.client as ws
    ws.loop.run_until_complete(self._connect())
    self._event_handler._do_without_validation(EVENT.encode())
    while True: time.sleep(1)
lark.ws.Client.start=start
raise SystemExit(main())
'''.replace('EVENT',repr(json.dumps(event())))
    async def spawn(*args,**kwargs):
        assert 'secret' not in args
        return await create_process(sys.executable,'-u','-c',script,**kwargs)
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
    ch=channel()
    try:
        await asyncio.wait_for(ch.start(),10)
        process=ch._process
        assert ch.is_running
        message=await asyncio.wait_for(ch.bus.consume_inbound(),3)
        assert message.message_id=='om_1'
    finally:
        await ch.stop()
    assert process.returncode is not None
    assert not ch.is_running


@pytest.mark.asyncio
async def test_token_refresh_is_shared_between_concurrent_sends():
    auth_calls=0
    async def handle(request):
        nonlocal auth_calls
        if '/auth/' in str(request.url):
            auth_calls+=1
            await asyncio.sleep(.01)
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        return httpx.Response(200,json={'code':0})
    ch=channel();ch._http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        await asyncio.gather(ch.send(OutboundMessage('feishu','a','hi',event_id='1')),
                             ch.send(OutboundMessage('feishu','b','hi',event_id='2')))
        assert auth_calls==1
    finally:
        await ch.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http', 'transport'])
async def test_transient_token_failure_is_retried_before_sending(failure):
    from cota.channels.events import OutboundMessage
    auth_calls, sent = 0, []
    def respond(request):
        nonlocal auth_calls
        if '/auth/' in request.url.path:
            auth_calls += 1
            if auth_calls == 1:
                if failure == 'transport':
                    raise httpx.ConnectError('temporarily unavailable', request=request)
                return httpx.Response(503)
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'test-token', 'expire': 7200})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'code': 0})
    channel = FeishuChannel({'app_id': 'cli_test', 'app_secret': 'secret'}, MessageBus())
    channel._http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await channel.send(OutboundMessage(channel='feishu', chat_id='oc_chat', content='reply', event_id='event-1'))
        assert auth_calls == 2 and len(sent) == 1
    finally:
        await channel.stop()

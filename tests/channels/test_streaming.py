"""Public previews are ephemeral, bounded and bound to the trusted route."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cota.channels.base import BaseChannel
from cota.channels.cmdline import CmdlineChannel
from cota.channels.events import InboundMessage, OutboundMessage
from cota.channels.queue import MessageBus
from cota.channels.web.base import WebChannel
from cota.channels.web.transport import Connection, WebSocketTransport
from cota.conversation import message_record
from cota.dst import DST
from cota.processor import Processor
from cota.store import MemoryStore


def frame(session='s', phase='delta', **kw):
    return {'session_id': session, 'run_id': 'run', 'request_id': 'req', 'phase': phase, **kw}


async def test_web_previews_use_separate_bounded_queue_without_cursor_or_replay():
    transport = WebSocketTransport({}, MessageBus())
    active = Connection(SimpleNamespace(), managed=True, sessions={'s'}, cursors={'s': 7})
    other = Connection(SimpleNamespace(), managed=True, sessions={'other'})
    replay = Connection(SimpleNamespace(), managed=True, sessions={'s'}, replaying=True, replay_session='s')
    transport._connections = {'s': {active, other, replay}}
    await transport.send_stream('s', frame(text='hello', prompt='private'))
    result = active.stream_queue.get_nowait()
    assert result == {'type': 'stream', **frame(text='hello')}
    assert active.queue.empty() and active.pending.empty() and active.cursors == {'s': 7}
    assert other.stream_queue.empty() and replay.stream_queue.empty()
    await transport.send_stream('s', frame('other', text='injected'))
    assert active.stream_queue.empty()
    for _ in range(500):
        await asyncio.wait_for(transport.send_stream('s', frame(text='x')), .1)
    assert active.stream_queue.qsize() <= 32
    await transport.publish('s', {'type':'ready'})
    assert active.queue.get_nowait() == {'type':'ready'}


async def test_stream_sender_rechecks_authorization_and_unsubscribe():
    transport = WebSocketTransport({}, MessageBus())
    service = SimpleNamespace(authenticate=AsyncMock(return_value='u'), authorize=AsyncMock(side_effect=PermissionError()))
    transport.bind(service)
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    connection = Connection(socket, user_id='u', session_id='s', managed=True, sessions={'s'})
    transport._connections['s'] = {connection}
    await transport.send_stream('s', frame(text='secret'))
    await asyncio.wait_for(transport._send_loop(connection), 1)
    assert all('secret' not in call.args[0] for call in socket.send.call_args_list)
    socket.close.assert_awaited()


async def test_cmdline_prints_preview_once_and_final_missing_tail(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    await channel.send_stream(sid, frame(sid, 'start'))
    await channel.send_stream(sid, frame(sid, text='hello'))
    assert capsys.readouterr().err == 'Bot: hello'
    await channel.send_stream(sid, frame(sid, 'end'))
    await channel.send(OutboundMessage('cmdline', channel._session_id, 'hello world',
                                      session_id=sid, metadata={'request_id':'req'}))
    assert capsys.readouterr().err == ' world\n'
    await channel.send_stream(sid, frame(sid, text='late'))
    await channel.send_stream(sid, frame('other', 'start'))
    assert capsys.readouterr().err == ''
    await channel.send(OutboundMessage('cmdline', channel._session_id, 'next', session_id=sid))
    assert capsys.readouterr().err == 'Bot: next\n'


async def test_cmdline_interrupted_preview_and_bounded_state(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    await channel.send_stream(sid, frame(sid, 'start'))
    await channel.send_stream(sid, frame(sid, text='partial'))
    await channel.send_stream(sid, frame(sid, 'error'))
    assert capsys.readouterr().err == 'Bot: partial\n[回复已中断]\n'
    await channel.send_stream(sid, frame(sid, text='late'))
    assert capsys.readouterr().err == ''


def test_public_projection_exposes_only_opaque_request_identity():
    event = {'event_id':'e', 'sequence':1, 'timestamp':2, 'type':'bot_utter',
             'payload':{'text':'public', 'llm':{'request_id':'req', 'prompt':'private'}}}
    projected = message_record('s', event)
    assert projected['request_id'] == 'req' and 'llm' not in projected
    event['payload'] = {'text':'commentary', 'metadata':{'request_id':'tool-req'}}
    assert message_record('s', event)['request_id'] == 'tool-req'


async def test_processor_stream_callback_independent_of_durable_callback(mock_agent):
    processor = Processor(mock_agent, MemoryStore())
    processor.dst = DST('s', agent=mock_agent)
    callback = AsyncMock()
    processor.set_stream_callback(callback)
    runtime = await processor._create_runtime('s')
    assert runtime._stream_callback is callback


async def test_application_binds_stream_to_actual_channel_session(mock_agent):
    from cota.application import Application
    app = Application(mock_agent)
    channel = SimpleNamespace(supports_streaming=True, durable_delivery=True,
                              delivery_scope='scope', send_stream=AsyncMock())
    app.runner.get_channel = lambda name: channel
    inbound = InboundMessage('web', 'u', 's', 'hello')
    processor = app._processor(inbound, on_reply=AsyncMock())
    await processor._stream_callback(frame('web:s', text='public'))
    await processor._stream_callback(frame('other', text='injected'))
    channel.send_stream.assert_awaited_once_with('web:s', frame('web:s', text='public'))
    assert BaseChannel.supports_streaming is False and WebChannel.supports_streaming is True


async def test_cmdline_final_before_preview_does_not_resurrect_output(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    await channel.send(OutboundMessage('cmdline', channel._session_id, 'final', session_id=sid,
                                      metadata={'request_id':'req'}))
    assert capsys.readouterr().err == 'Bot: final\n'
    await channel.send_stream(sid, frame(sid, 'start'))
    await channel.send_stream(sid, frame(sid, text='late'))
    assert capsys.readouterr().err == ''


async def test_cmdline_stream_state_is_bounded_without_buffering_text(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    for i in range(100):
        start = {**frame(sid, 'start'), 'request_id':str(i)}
        await channel.send_stream(sid, start)
        await channel.send_stream(sid, {**start, 'phase':'delta', 'text':'x' * 1000})
        await channel.send_stream(sid, {**start, 'phase':'end'})
    assert len(channel._stream_requests) <= 64
    assert all('text' not in state for state in channel._stream_requests.values())
    capsys.readouterr()


async def test_terminal_tool_commentary_and_next_final_have_distinct_previews(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    for request, text in [('tool-commentary','Checking.'), ('answer','Done.')]:
        start = {**frame(sid, 'start'), 'request_id':request}
        await channel.send_stream(sid, start)
        await channel.send_stream(sid, {**start, 'phase':'delta', 'text':text})
        await channel.send_stream(sid, {**start, 'phase':'end'})
        await channel.send(OutboundMessage('cmdline', channel._session_id, text, session_id=sid,
                                          metadata={'request_id':request}))
    assert capsys.readouterr().err == 'Bot: Checking.\nBot: Done.\n'


async def test_durable_queue_retains_priority_over_preview_and_unsubscribed_preview_is_skipped():
    transport = WebSocketTransport({}, MessageBus())
    transport.bind(SimpleNamespace(authorize=AsyncMock(), authenticate=AsyncMock(return_value='u')))
    delivered = asyncio.Event()
    frames = []
    async def send(raw):
        frames.append(raw)
        delivered.set()
    connection = Connection(SimpleNamespace(send=send, close=AsyncMock()), managed=True,
                            user_id='u', session_id='s', sessions={'s'})
    transport._connections['s'] = {connection}
    await transport.send_stream('s', frame(text='must not deliver'))
    connection.queue.put_nowait({'type':'ready', 'session_id':'s'})
    assert (await transport._next_frame(connection))['type'] == 'ready'
    await transport.unsubscribe(connection, 's')
    connection.queue.put_nowait({'type':'error', 'session_id':'s', 'code':'busy'})
    task = asyncio.create_task(transport._send_loop(connection))
    try:
        await asyncio.wait_for(delivered.wait(), 1)
        await asyncio.sleep(0)
        assert all('must not deliver' not in raw for raw in frames)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_legacy_channel_gets_its_own_bound_stream_callback(mock_agent):
    processor = Processor(mock_agent, MemoryStore())
    processor.dst = DST('s', mock_agent)
    runtime = SimpleNamespace(set_channel_callback=lambda callback: None, set_stream_callback=lambda callback: setattr(runtime, 'stream', callback))
    processor._create_runtime = AsyncMock(return_value=runtime)
    processor._run_runtime = AsyncMock()
    channel = SimpleNamespace(supports_streaming=True, send_stream=AsyncMock(), send_response=AsyncMock())
    await processor._handle_bot_turn('s', channel)
    await runtime.stream(frame(text='public'))
    await runtime.stream(frame('elsewhere', text='private'))
    channel.send_stream.assert_awaited_once_with('s', frame(text='public'))


async def test_terminal_error_after_end_marks_uncommitted_preview_interrupted(capsys):
    channel = CmdlineChannel({}, MessageBus())
    sid = channel.session_key
    for phase in ['start', 'delta', 'end', 'error']:
        await channel.send_stream(sid, frame(sid, phase, **({'text':'partial'} if phase == 'delta' else {})))
    assert capsys.readouterr().err == 'Bot: partial\n[回复已中断]\n'

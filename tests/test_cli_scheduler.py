"""Scheduled shell inputs use the same serial intake as terminal messages."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cota import __main__ as cli
from cota.channels.queue import MessageBus


async def test_shell_scheduler_preserves_owner_and_session_without_direct_execution(tmp_path, monkeypatch):
    bus = MessageBus()
    saved = {}
    service = SimpleNamespace(start=AsyncMock(), list_jobs=AsyncMock(return_value=[]))
    service.set_callback = lambda fn: saved.update(callback=fn)
    monkeypatch.setattr('cota.executor.scheduler.SchedulerService', lambda **kwargs: service)
    monkeypatch.setattr('cota.executor.scheduler.set_scheduler_service', lambda _: None)
    agent = SimpleNamespace(create_processor=lambda: (_ for _ in ()).throw(AssertionError('must enqueue')))
    await cli._start_scheduler(agent, str(tmp_path), message_bus=bus)
    await saved['callback'](SimpleNamespace(id='job', name='reminder', session_id='cmdline:one',
                                           user_id='alice', payload={'text': 'hello'}))
    inbound = await bus.consume_inbound()
    assert inbound.sender_id == 'alice' and inbound.session_key == 'cmdline:one'
    assert inbound.content == '[定时提醒] hello'

"""Channel registration, discovery, and configuration boundaries."""

from importlib import import_module, metadata
from types import MappingProxyType, SimpleNamespace
import sys

import pytest

from cota.channels.base import BaseChannel
from cota.channels.queue import MessageBus


class RecordingChannel(BaseChannel):
    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def send(self, msg):
        pass


def registry_module():
    return import_module('cota.channels.registry')


def no_plugins(monkeypatch):
    monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs: [])
    return registry_module().ChannelRegistry()


def test_register_and_create_binds_instance_name_and_copies_config(monkeypatch):
    registry = no_plugins(monkeypatch)
    registry.register('recording', RecordingChannel)
    config = {'enabled': True, 'type': 'recording', 'allow_from': ['u1']}
    bus = MessageBus()
    channel = registry.create('team-chat', config, bus)
    assert isinstance(channel, RecordingChannel)
    assert channel.name == 'team-chat'
    assert channel.bus is bus
    assert channel.config == config
    assert channel.config is not config
    assert not channel.is_running
    assert config == {'enabled': True, 'type': 'recording', 'allow_from': ['u1']}


def test_type_defaults_to_instance_name(monkeypatch):
    registry = no_plugins(monkeypatch)
    registry.register('recording', RecordingChannel)
    assert isinstance(registry.create('recording', {}, MessageBus()), RecordingChannel)


def test_registry_registration_is_per_application(monkeypatch):
    first = no_plugins(monkeypatch)
    first.register('recording', RecordingChannel)
    second = registry_module().ChannelRegistry()
    with pytest.raises(ValueError, match='Unknown channel type.*recording'):
        second.create('recording', {}, MessageBus())


def test_installed_plugins_are_discovered_without_loading(monkeypatch):
    calls = []
    entry = SimpleNamespace(name='recording', load=lambda: calls.append('loaded') or RecordingChannel)
    def entry_points(**kwargs):
        assert kwargs == {'group': 'cota.channels'}
        return [entry]
    monkeypatch.setattr(metadata, 'entry_points', entry_points)
    registry = registry_module().ChannelRegistry()
    assert calls == []
    registry.create('team', {'type': 'recording'}, MessageBus())
    registry.create('other', {'type': 'recording'}, MessageBus())
    assert calls == ['loaded']


def test_builtins_are_import_strings_and_only_selected_type_is_loaded(monkeypatch):
    registry = no_plugins(monkeypatch)
    calls = []
    def load(module):
        calls.append(module)
        return SimpleNamespace(WebChannel=RecordingChannel, FeishuChannel=RecordingChannel,
                               CmdlineChannel=RecordingChannel)
    monkeypatch.setattr(registry_module(), 'import_module', load)
    assert calls == []
    assert isinstance(registry.create('office', {'type': 'feishu'}, MessageBus()), RecordingChannel)
    assert calls == ['cota.channels.platforms.feishu']


@pytest.mark.parametrize('name', ['web', 'feishu', 'cmdline', 'duplicate'])
def test_duplicate_entry_points_including_builtin_collisions_fail(monkeypatch, name):
    entries = [SimpleNamespace(name=name, load=lambda: RecordingChannel)]
    if name == 'duplicate':
        entries.append(SimpleNamespace(name=name, load=lambda: RecordingChannel))
    monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs: entries)
    with pytest.raises(ValueError, match=f'Duplicate channel type.*{name}'):
        registry_module().ChannelRegistry()


def test_duplicate_explicit_registration_fails(monkeypatch):
    registry = no_plugins(monkeypatch)
    registry.register('recording', RecordingChannel)
    with pytest.raises(ValueError, match='Duplicate channel type.*recording'):
        registry.register('recording', RecordingChannel)


def test_explicit_import_factory(monkeypatch):
    registry = no_plugins(monkeypatch)
    monkeypatch.setitem(sys.modules, 'fake_channel_package', SimpleNamespace(make=RecordingChannel))
    channel = registry.create('team', {'factory': 'fake_channel_package:make'}, MessageBus())
    assert isinstance(channel, RecordingChannel)
    assert channel.name == 'team'


def test_registered_import_factory_is_lazy(monkeypatch):
    registry = no_plugins(monkeypatch)
    registry.register('recording', 'fake_channel_package:make')
    monkeypatch.setitem(sys.modules, 'fake_channel_package', SimpleNamespace(make=RecordingChannel))
    assert isinstance(registry.create('recording', {}, MessageBus()), RecordingChannel)


@pytest.mark.parametrize('factory', ['no_such_channel_package:make', 'sys:no_such_factory'])
def test_factory_import_errors_identify_instance_and_factory(monkeypatch, factory):
    registry = no_plugins(monkeypatch)
    with pytest.raises(ValueError, match='team.*factory') as error:
        registry.create('team', {'factory': factory}, MessageBus())
    assert factory in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize('factory', [42, lambda config, bus: object()])
def test_invalid_registered_factory_or_result_is_rejected(monkeypatch, factory):
    registry = no_plugins(monkeypatch)
    with pytest.raises(ValueError, match='factory|BaseChannel'):
        registry.register('recording', factory)
        registry.create('recording', {}, MessageBus())


def test_non_callable_import_target_fails(monkeypatch):
    registry = no_plugins(monkeypatch)
    monkeypatch.setitem(sys.modules, 'fake_channel_package', SimpleNamespace(make=42))
    with pytest.raises(ValueError, match='team.*callable'):
        registry.create('team', {'factory': 'fake_channel_package:make'}, MessageBus())


def test_factory_exception_has_context(monkeypatch):
    registry = no_plugins(monkeypatch)
    def broken(config, bus):
        raise RuntimeError('missing credential')
    registry.register('recording', broken)
    with pytest.raises(ValueError, match='team.*RuntimeError') as error:
        registry.create('team', {'type': 'recording'}, MessageBus())
    assert error.value.__cause__ is None


def test_async_factory_is_rejected_without_leaking_coroutine(monkeypatch):
    registry = no_plugins(monkeypatch)
    async def make(config, bus):
        return RecordingChannel(config, bus)
    registry.register('recording', make)
    with pytest.raises(ValueError, match='BaseChannel|synchronous'):
        registry.create('recording', {}, MessageBus())


def test_entry_point_load_error_has_context(monkeypatch):
    def broken():
        raise ImportError('optional SDK unavailable')
    monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs: [SimpleNamespace(name='chat', load=broken)])
    registry = registry_module().ChannelRegistry()
    with pytest.raises(ValueError, match='team.*chat.*ImportError'):
        registry.create('team', {'type': 'chat'}, MessageBus())


def test_unknown_type_error_names_instance_and_available_plugins(monkeypatch):
    registry = no_plugins(monkeypatch)
    with pytest.raises(ValueError, match='Unknown channel type.*absent') as error:
        registry.create('team', {'type': 'absent'}, MessageBus())
    assert 'team' in str(error.value)
    assert 'web' in str(error.value)
    assert 'cota.channels' in str(error.value)


def test_validate_channels_accepts_disabled_unknown_and_copies_mappings(monkeypatch):
    monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs: pytest.fail('validation discovered plugins'))
    settings = MappingProxyType({'enabled': False, 'type': 'uninstalled', 'token': 'private'})
    source = MappingProxyType({'future-chat': settings})
    result = registry_module().validate_channels(source)
    assert result == {'future-chat': dict(settings)}
    assert isinstance(result, dict)
    assert isinstance(result['future-chat'], dict)
    assert result['future-chat'] is not settings


@pytest.mark.parametrize('config', [None, [], 'web', {'web': None}, {'web': []}])
def test_validate_channels_requires_objects(config):
    with pytest.raises(ValueError, match='object|mapping'):
        registry_module().validate_channels(config)


@pytest.mark.parametrize('enabled', [0, 1, 'true', None, []])
def test_enabled_must_be_boolean(enabled):
    with pytest.raises(ValueError, match='enabled.*boolean'):
        registry_module().validate_channels({'chat': {'enabled': enabled}})


@pytest.mark.parametrize('name', ['', 'Upper', 'a.b', '../path', 'has space', 'a/b', '-prefix', 'a' * 65, 42])
def test_instance_name_must_be_url_safe_identifier(name):
    with pytest.raises(ValueError, match='name|identifier'):
        registry_module().validate_channels({name: {}})


@pytest.mark.parametrize('kind', ['', 'Upper', 'a.b', 'a/b', 'a' * 65, None, 7])
def test_type_must_be_url_safe_identifier(kind):
    with pytest.raises(ValueError, match='type|identifier'):
        registry_module().validate_channels({'chat': {'type': kind}})


@pytest.mark.parametrize('factory', ['', 'no_colon', ':func', 'package:', 'a:b:c', None, 42])
def test_factory_must_be_module_callable_reference(factory):
    with pytest.raises(ValueError, match='factory'):
        registry_module().validate_channels({'chat': {'factory': factory}})


def test_factory_and_explicit_type_are_mutually_exclusive():
    with pytest.raises(ValueError, match='factory.*type|type.*factory'):
        registry_module().validate_channels({'chat': {'type': 'custom', 'factory': 'module:make'}})


@pytest.mark.parametrize('name,settings', [('browser', {'type': 'web'}), ('web', {'type': 'recording'}),
                                          ('web', {'factory': 'package:make'})])
def test_web_transport_requires_reserved_web_instance(name, settings):
    with pytest.raises(ValueError, match='web'):
        registry_module().validate_channels({name: settings})


def test_entry_point_runtime_load_error_has_context(monkeypatch):
    def broken():
        raise RuntimeError('plugin initialization failed')
    monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs: [SimpleNamespace(name='chat', load=broken)])
    registry = registry_module().ChannelRegistry()
    with pytest.raises(ValueError, match='team.*chat.*RuntimeError') as error:
        registry.create('team', {'type': 'chat'}, MessageBus())
    assert error.value.__cause__ is None


@pytest.mark.parametrize('name', ['Upper', 'bad/name', '', 'a' * 65])
def test_invalid_registration_name_is_rejected(monkeypatch, name):
    registry = no_plugins(monkeypatch)
    with pytest.raises(ValueError, match='name|identifier'):
        registry.register(name, RecordingChannel)


@pytest.mark.parametrize('name', ['team_chat', 'team-chat', 'a', 'a' * 64])
def test_valid_instance_names_are_preserved(name):
    config = {name: {'enabled': False}}
    assert registry_module().validate_channels(config) == config


@pytest.mark.parametrize('stage', ['load', 'construct'])
def test_factory_failures_do_not_expose_secrets_in_normal_traceback(monkeypatch, stage):
    import traceback

    secret = 'SENTINEL_PRIVATE_CREDENTIAL'
    registry = no_plugins(monkeypatch)
    if stage == 'load':
        def broken():
            raise RuntimeError('cannot import using token=' + secret)
        monkeypatch.setattr(metadata, 'entry_points', lambda **kwargs:
                            [SimpleNamespace(name='broken', load=broken)])
        registry = registry_module().ChannelRegistry()
    else:
        def broken(config, bus):
            raise RuntimeError('cannot connect using token=' + config['token'])
        registry.register('broken', broken)
    with pytest.raises(ValueError, match='team.*broken.*RuntimeError') as error:
        registry.create('team', {'type': 'broken', 'token': secret}, MessageBus())
    assert secret not in str(error.value)
    formatted = ''.join(traceback.format_exception(error.type, error.value, error.tb))
    assert secret not in formatted


@pytest.mark.asyncio
async def test_invalid_factory_returned_task_is_cancelled(monkeypatch):
    import asyncio

    registry = no_plugins(monkeypatch)
    tasks = []
    async def listener():
        await asyncio.Event().wait()
    def factory(config, bus):
        task = asyncio.create_task(listener())
        tasks.append(task)
        return task
    registry.register('bad_async', factory)
    try:
        with pytest.raises(ValueError, match='synchronously return BaseChannel'):
            registry.create('team', {'type': 'bad_async'}, MessageBus())
        await asyncio.sleep(0)
        assert tasks[0].cancelled()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_invalid_factory_returned_failed_future_is_observed(monkeypatch):
    import asyncio
    import gc
    import weakref

    registry = no_plugins(monkeypatch)
    loop = asyncio.get_running_loop()
    unobserved = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: unobserved.append(context))
    future = loop.create_future()
    future.set_exception(RuntimeError('future failure'))
    future_ref = weakref.ref(future)
    results = [future]
    registry.register('bad_async', lambda config, bus: results.pop())
    try:
        try:
            registry.create('team', {'type': 'bad_async'}, MessageBus())
        except ValueError:
            pass
        else:
            pytest.fail('Future accepted as channel')
        del future
        await asyncio.sleep(0)
        gc.collect()
        assert future_ref() is None
        assert unobserved == []
    finally:
        loop.set_exception_handler(previous)

"""The maintained channel surface and its configuration boundary."""

import pytest

from cota.channels import ChannelManager, CmdlineChannel, FeishuChannel, MessageBus, WebChannel


@pytest.mark.parametrize('name', ['telegram', 'discord', 'qq', 'dingtalk', 'slack', 'unknown'])
def test_uninstalled_enabled_channel_configuration_is_rejected(name):
    with pytest.raises(ValueError, match='Unknown channel'):
        ChannelManager({'channels': {name: {'enabled': True}}}, MessageBus())


def test_disabled_uninstalled_plugin_is_not_loaded():
    assert ChannelManager({'channels': {'unknown': {'enabled': False}}}, MessageBus()).channels == {}


def test_supported_channels_initialize_together_without_connecting():
    bus = MessageBus()
    manager = ChannelManager({'channels': {
        'web': {'enabled': True},
        'feishu': {'enabled': True, 'app_id': 'test-app', 'allow_from': ['ou_test']},
        'cmdline': {'enabled': True},
    }}, bus)
    assert set(manager.channels) == {'web', 'feishu', 'cmdline'}
    for name, kind in [('web', WebChannel), ('feishu', FeishuChannel), ('cmdline', CmdlineChannel)]:
        assert isinstance(manager.channels[name], kind)
        assert manager.channels[name].bus is bus
        assert not manager.channels[name].is_running


def test_disabled_supported_channels_are_not_initialized():
    manager = ChannelManager({'channels': {
        name: {'enabled': False} for name in ('web', 'feishu', 'cmdline')
    }}, MessageBus())
    assert manager.channels == {}

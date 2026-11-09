"""The maintained channel surface and its configuration boundary."""

import pytest

from cota.channels import ChannelManager, CmdlineChannel, FeishuChannel, MessageBus, WebChannel


@pytest.mark.parametrize('name', ['telegram', 'discord', 'qq', 'dingtalk', 'slack', 'unknown'])
@pytest.mark.parametrize('enabled', [True, False])
def test_unsupported_channel_configuration_is_rejected(name, enabled):
    with pytest.raises(ValueError, match='Unsupported channel'):
        ChannelManager({'channels': {name: {'enabled': enabled}}}, MessageBus())


def test_supported_channels_initialize_together_without_connecting():
    bus = MessageBus()
    manager = ChannelManager({'channels': {
        'web': {'enabled': True},
        'feishu': {'enabled': True, 'allow_from': ['ou_test']},
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

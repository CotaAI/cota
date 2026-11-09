"""Per-application channel factories with lazy installed-plugin loading.

Factories receive ``(settings, bus)`` and synchronously return a BaseChannel.
Constructors should only configure the adapter; network work belongs in start().
Installed packages expose factories through the ``cota.channels`` entry-point group.
"""

import asyncio
from collections.abc import Callable, Mapping
from importlib import import_module, metadata
import inspect
import re
from typing import Any

from .base import BaseChannel
from .queue import MessageBus


_BUILTINS = {
    'web': 'cota.channels.web:WebChannel',
    'feishu': 'cota.channels.platforms.feishu:FeishuChannel',
    'cmdline': 'cota.channels.cmdline:CmdlineChannel',
}
_IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*')
_IMPORT_REFERENCE = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', re.ASCII)


def _validate_name(name: str, path: str) -> None:
    if not isinstance(name, str) or len(name) > 64 or not _IDENTIFIER.fullmatch(name):
        raise ValueError(
            f'{path} must be a lowercase identifier of at most 64 characters '
            '(letters, digits, underscores, or hyphens; starting with a letter)'
        )


def _validate_reference(reference: str, path: str) -> None:
    if not isinstance(reference, str) or not _IMPORT_REFERENCE.fullmatch(reference):
        raise ValueError(f'{path} must be a module:callable import reference')


def validate_channels(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and copy a channels mapping without importing adapter code.

    Missing enabled flags mean False; missing types mean the instance name.
    Unknown types are allowed here, including disabled, uninstalled plugins.
    Resolution is the registry's responsibility when creating enabled adapters.
    Adapter-specific options are preserved for the adapter's own validation.
    """
    if not isinstance(config, Mapping):
        raise ValueError('channels must be an object (mapping)')
    result = {}
    for name, original in config.items():
        _validate_name(name, 'channel instance name')
        if not isinstance(original, Mapping):
            raise ValueError(f'channels.{name} must be an object (mapping)')
        settings = dict(original)
        if type(settings.get('enabled', False)) is not bool:
            raise ValueError(f'channels.{name}.enabled must be boolean')
        if 'factory' in settings:
            if 'type' in settings:
                raise ValueError(f'channels.{name}.factory and type are mutually exclusive')
            _validate_reference(settings['factory'], f'channels.{name}.factory')
            if name == 'web':
                raise ValueError('The web instance is reserved for the built-in web channel')
        else:
            kind = settings.get('type', name)
            _validate_name(kind, f'channels.{name}.type')
            if (kind == 'web') != (name == 'web'):
                raise ValueError('The built-in web channel must use the reserved web instance name')
        result[name] = settings
    return result


class ChannelRegistry:
    """Resolve built-in, installed, or explicitly configured channel factories.

    Discovery reads package metadata only. A selected factory is imported on its
    first create() call and cached within this registry. Duplicate names are
    rejected so package installation cannot silently replace another adapter.
    """

    def __init__(self):
        self._factories: dict[str, Callable | str] = dict(_BUILTINS)
        self._entry_points = {}
        for entry_point in metadata.entry_points(group='cota.channels'):
            name = entry_point.name
            _validate_name(name, 'channel entry-point name')
            self._check_duplicate(name)
            self._entry_points[name] = entry_point

    def _check_duplicate(self, name: str) -> None:
        if name in self._factories or name in self._entry_points:
            raise ValueError(f'Duplicate channel type {name!r}; channel names must be unique')

    def register(self, name: str, factory: Callable | str) -> None:
        """Register a callable or lazy module:callable reference for this app."""
        _validate_name(name, 'channel type name')
        self._check_duplicate(name)
        if isinstance(factory, str):
            _validate_reference(factory, f'channel {name!r} factory')
        elif not callable(factory):
            raise ValueError(f'Channel {name!r} factory must be callable or a module:callable reference')
        self._factories[name] = factory

    @staticmethod
    def _import_factory(reference: str):
        module_name, attribute = reference.split(':')
        target = import_module(module_name)
        for part in attribute.split('.'):
            target = getattr(target, part)
        return target

    def create(self, instance_name: str, settings: Mapping[str, Any], bus: MessageBus) -> BaseChannel:
        """Construct a configured channel; the manager owns binding and startup.

        Enabled flags are validated but creation is explicit: callers choose which
        instances to create, normally by skipping disabled settings beforehand.
        """
        config = validate_channels({instance_name: settings})[instance_name]
        explicit = config.get('factory')
        kind = config.get('type', instance_name)
        label = explicit or kind
        if not explicit and kind not in self._factories and kind not in self._entry_points:
            available = ', '.join(sorted(self._factories.keys() | self._entry_points.keys()))
            raise ValueError(
                f'Unknown channel type {kind!r} for instance {instance_name!r}. '
                f'Available types: {available}. Install a cota.channels plugin '
                'or configure a module:callable factory.'
            )
        try:
            if explicit:
                factory = self._import_factory(explicit)
            elif kind in self._factories:
                factory = self._factories[kind]
                if isinstance(factory, str):
                    factory = self._import_factory(factory)
            else:
                factory = self._entry_points[kind].load()
        except Exception as error:
            raise ValueError(
                f'Channel {instance_name!r} could not load factory {label!r} ({type(error).__name__})'
            ) from None
        if not callable(factory):
            raise ValueError(f'Channel {instance_name!r} factory {label!r} must be callable')
        if not explicit:
            self._factories[kind] = factory
        try:
            channel = factory(config, bus)
        except Exception as error:
            raise ValueError(
                f'Channel {instance_name!r} factory {label!r} failed ({type(error).__name__})'
            ) from None
        if not isinstance(channel, BaseChannel):
            # Avoid unawaited-coroutine warnings from accidentally async factories.
            if inspect.iscoroutine(channel):
                channel.close()
            elif asyncio.isfuture(channel):
                channel.cancel()
                if channel.done():
                    self._observe_rejected_future(channel)
                else:
                    channel.add_done_callback(self._observe_rejected_future)
            raise ValueError(
                f'Channel {instance_name!r} factory {label!r} must synchronously return BaseChannel; '
                f'got {type(channel).__name__}'
            )
        channel.name = instance_name
        return channel

    @staticmethod
    def _observe_rejected_future(future):
        if not future.cancelled():
            future.exception()

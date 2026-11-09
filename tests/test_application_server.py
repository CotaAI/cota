from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from cota.server import create_app
from cota.store import MemoryStore
from cota.channels.web.access import ExternalAccess


def agent():
    return SimpleNamespace(store=MemoryStore(),name='Test',cleanup=AsyncMock())


def test_feishu_only_does_not_force_web_routes():
    app=create_app(agent(),channel_config={'web':{'enabled':False},'feishu':{
        'enabled':True,'app_id':'cli','app_secret':'secret','allow_from':['*']}})
    paths={route.path for route in app.router.routes}
    assert 'api/health' in paths
    assert 'ws' not in paths and 'api/guests' not in paths
    assert app.ctx.web_service is None
    assert app.ctx.application.runner is app.ctx.runner


def test_all_disabled_is_configuration_error():
    with pytest.raises(ValueError,match='enabled'):
        create_app(agent(),channel_config={'web':{'enabled':False}})


def test_cli_configuration_loads_external_access_factory(tmp_path):
    (tmp_path/'access.py').write_text('''from cota.channels.web.access import ExternalAccess
async def authenticate(token): return 'user'
async def authorize(user, session): return session == 'allowed'
def create_access(): return ExternalAccess(authenticate, authorize)
''')
    app=create_app(agent(),config_path=str(tmp_path),channel_config={'web':{
        'enabled':True,'access_factory':'./access.py:create_access'}})
    assert isinstance(app.ctx.web_service.access,ExternalAccess)
    assert app.ctx.web_service.access.allow_guests is False


def test_access_factory_and_explicit_callbacks_are_not_ambiguous():
    with pytest.raises(ValueError,match='access_factory'):
        create_app(agent(),channel_config={'web':{'enabled':True,'access_factory':'bad:factory'}},
                   authenticate=AsyncMock(),authorize=AsyncMock())


def test_endpoint_channel_settings_override_agent_without_losing_defaults(tmp_path):
    from cota.__main__ import _load_channel_config
    (tmp_path/'agent.yml').write_text('channels:\n  web:\n    enabled: false\n  feishu:\n    enabled: true\n    allow_from: [ou_test]\n')
    (tmp_path/'endpoints.yml').write_text('channels:\n  feishu:\n    app_id: cli_test\n    app_secret: test-secret\n')
    assert _load_channel_config(str(tmp_path)) == {
        'web': {'enabled': False},
        'feishu': {'enabled': True, 'allow_from': ['ou_test'], 'app_id': 'cli_test', 'app_secret': 'test-secret'}}


@pytest.mark.parametrize('contents', ['channels: []', 'channels:\n  feishu: true'])
def test_invalid_channel_config_has_clear_error(tmp_path, contents):
    from cota.__main__ import _load_channel_config
    (tmp_path/'endpoints.yml').write_text(contents)
    with pytest.raises(ValueError, match='channels'):
        _load_channel_config(str(tmp_path))

"""Public server metadata through the real HTTP listener."""

import pytest

from cota import __version__
from tests.test_web_app_integration import running_app


@pytest.mark.asyncio
async def test_server_metadata_and_removed_agent_directory(tmp_path):
    async def unused_model(**kwargs):
        raise AssertionError('Metadata endpoints must not call the model')

    async with running_app(tmp_path, unused_model) as server:
        async with server.http.get(server.url + '/version') as response:
            assert response.status == 200
            assert await response.json() == {'version': __version__}
        async with server.http.get(server.url + '/api/health') as response:
            assert response.status == 200
            data = await response.json()
            assert data['success'] is True and data['bot'] == 'Socket test bot'
            assert data['channels']['web']['running'] is True
        async with server.http.get(server.url + '/api/agent/list') as response:
            assert response.status == 404

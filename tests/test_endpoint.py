"""Tests for REST API endpoints.

These tests verify endpoint routing and response structure without
requiring the sanic_testing package.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(scope="module")
def endpoint_app():
    """Create a Sanic app with mocked agent. Module-scoped to avoid duplicate name error."""
    from sanic import Sanic
    # Clean up any existing registration so tests can run standalone
    Sanic._app_registry.pop("cota", None)

    from tests.conftest import MockAgent
    mock_agent = MockAgent()
    from cota.store import MemoryStore
    mock_agent.store = MemoryStore()

    from cota.server import create_app
    return create_app(agent=mock_agent)



class TestVersionEndpointRouting:
    """Test /version endpoint is registered and returns version info."""

    def test_version_route_exists(self, endpoint_app):
        """Test that the /version route is registered on the app."""
        route_paths = [str(route.path) for route in endpoint_app.router.routes]
        assert any("version" in p for p in route_paths)

    def test_version_handler_returns_version_key(self, endpoint_app):
        """Test that the version handler function returns a response with 'version' key."""
        import asyncio
        import json
        from cota import __version__

        # Find the version handler by inspecting the routes
        version_handler = None
        for route in endpoint_app.router.routes:
            if "version" in str(route.path):
                version_handler = route.handler
                break

        assert version_handler is not None

        mock_request = MagicMock()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(version_handler(mock_request))
        finally:
            loop.close()

        body = json.loads(result.body)
        assert "version" in body
        assert body["version"] == __version__


class TestHealthEndpointRouting:
    """Test /api/health endpoint is registered."""

    def test_health_route_exists(self, endpoint_app):
        """Test that the /api/health route is registered."""
        route_paths = [str(route.path) for route in endpoint_app.router.routes]
        assert any("health" in p for p in route_paths)

"""Tests for cota.executor.tools.registry — ToolPolicy, ToolRegistry"""

import pytest
from cota.executor.tools.base import Tool
from cota.executor.tools.registry import (
    ToolPolicy,
    ToolRegistry,
    _expand_groups,
)


def _make_tool(name, builtin=False, enabled=True):
    """Helper to create a minimal tool for testing."""

    class T(Tool):
        @property
        def name(self):
            return name

        @property
        def description(self):
            return f"Test tool {name}"

        @property
        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        @property
        def builtin(self):
            return builtin

        @property
        def enabled(self):
            return enabled

        async def execute(self, **kwargs):
            return {"content": []}

    return T()


class TestExpandGroups:

    def test_expand_known_group(self):
        result = _expand_groups(["group:network"])
        assert "http_request" in result

    def test_expand_plain_name(self):
        result = _expand_groups(["exec", "http_request"])
        assert result == {"exec", "http_request"}

    def test_expand_mixed(self):
        result = _expand_groups(["group:network", "lookup"])
        assert "lookup" in result
        assert "http_request" in result

    def test_expand_unknown_group(self):
        with pytest.raises(ValueError, match="Unknown tool group"):
            _expand_groups(["group:nonexistent"])


class TestToolPolicy:

    def test_default_allows_all(self):
        policy = ToolPolicy()
        tool = _make_tool("anything")
        assert policy.is_allowed(tool) is True

    def test_empty_allow_disables_all(self):
        policy = ToolPolicy(allow=[])
        assert policy.is_allowed("http_request") is False
        assert policy.is_allowed(_make_tool("custom")) is False

    def test_deny(self):
        policy = ToolPolicy(deny=["exec"])
        assert policy.is_allowed(_make_tool("exec")) is False
        assert policy.is_allowed(_make_tool("read_file")) is True

    def test_allow(self):
        policy = ToolPolicy(allow=["read_file", "write_file"])
        assert policy.is_allowed(_make_tool("read_file")) is True
        assert policy.is_allowed(_make_tool("exec")) is False

    def test_deny_wins_over_allow(self):
        policy = ToolPolicy(allow=["lookup", "update"], deny=["update"])
        assert policy.is_allowed(_make_tool("lookup")) is True
        assert policy.is_allowed(_make_tool("update")) is False

    def test_builtin_attribute_cannot_bypass_policy(self):
        policy = ToolPolicy(deny=["protected"])
        tool = _make_tool("protected", builtin=True)
        assert policy.is_allowed(tool) is False

    def test_string_name_support(self):
        policy = ToolPolicy(deny=["exec"])
        assert policy.is_allowed("exec") is False
        assert policy.is_allowed("read_file") is True

    def test_group_deny(self):
        policy = ToolPolicy(deny=["group:network"])
        assert policy.is_allowed(_make_tool("http_request")) is False
        assert policy.is_allowed(_make_tool("exec")) is True


class TestToolRegistry:

    def test_registry_starts_empty(self):
        assert ToolRegistry().list_tools() == []

    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _make_tool("my_tool")
        reg.register(tool)
        assert reg.get("my_tool") is tool
        assert reg.get("nonexistent") is None

    def test_list_tools(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg.list_tools()) == 2
        assert set(reg.list_tool_names()) == {"a", "b"}

    def test_get_allowed_tools_no_policy(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg.get_allowed_tools()) == 2

    def test_get_allowed_tools_with_policy(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        reg.set_policy(ToolPolicy(deny=["a"]))
        allowed = reg.get_allowed_tools()
        names = [t.name for t in allowed]
        assert "a" not in names
        assert "b" in names

    def test_disabled_tools_filtered(self):
        reg = ToolRegistry()
        reg.register(_make_tool("active", enabled=True))
        reg.register(_make_tool("disabled", enabled=False))
        allowed = reg.get_allowed_tools()
        names = [t.name for t in allowed]
        assert "active" in names
        assert "disabled" not in names

    @pytest.mark.asyncio
    async def test_cleanup(self):
        reg = ToolRegistry()
        tool = _make_tool("clean_me")
        reg.register(tool)
        await reg.cleanup()  # should not raise


@pytest.mark.parametrize('name', ['read', 'write', 'edit', 'bash', 'grep', 'find', 'ls', 'powershell', 'http_request'])
def test_registration_rejects_reserved_names_immediately(name):
    registry = ToolRegistry()
    with pytest.raises(ValueError, match='reserved'):
        registry.register(_make_tool(name))
    assert registry.list_tools() == []


def test_registration_cannot_silently_replace_a_tool():
    registry = ToolRegistry()
    original = _make_tool('lookup')
    registry.register(original)
    with pytest.raises(ValueError, match='already registered'):
        registry.register(_make_tool('lookup'))
    assert registry.get('lookup') is original


@pytest.mark.parametrize('name', ['', 'bad name', 'group:network', 'a/b'])
def test_registration_rejects_invalid_names(name):
    with pytest.raises(ValueError, match='Invalid tool name'):
        ToolRegistry().register(_make_tool(name))


@pytest.mark.parametrize('key', ['allow', 'deny'])
def test_policy_references_are_validated_after_application_registration(key):
    registry = ToolRegistry()
    registry.set_policy(ToolPolicy(**{key: ['lookup', 'http_request']}))
    with pytest.raises(ValueError, match='Unknown configured tools.*lookup'):
        registry.validate()
    registry.register(_make_tool('lookup'))
    registry.validate()

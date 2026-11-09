"""Execution bindings of generic adapters must not leak between users."""

from cota.executor.tools.base import FunctionTool, create_tool_schema


def test_execution_binding_is_private_and_retains_handler():
    original = FunctionTool('lookup', 'lookup', create_tool_schema({}), lambda: {})
    first = original.for_execution('alice', service_mode=True)
    second = original.for_execution('bob', service_mode=False)
    assert first is not original and second is not original and first is not second
    assert first._service_mode is True
    assert second._service_mode is False
    assert original._service_mode is False
    assert first._handler is original._handler

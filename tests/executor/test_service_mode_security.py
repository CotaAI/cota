"""Execution bindings of generic adapters must not leak between users."""

from cota.executor.tools.base import FunctionTool, create_tool_schema


def test_execution_binding_is_private_and_retains_handler():
    original = FunctionTool('lookup', 'lookup', create_tool_schema({}), lambda: {})
    first = original.for_execution('alice')
    second = original.for_execution('bob')
    assert first is not original and second is not original and first is not second
    assert first._handler is original._handler

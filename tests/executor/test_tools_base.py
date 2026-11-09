"""Tests for cota.executor.tools.base — Tool, FunctionTool, ToolWrapper"""

import pytest
from cota.executor.tools.base import (
    FunctionTool,
    ToolWrapper,
    create_tool_schema,
)


class TestCreateToolSchema:

    def test_basic(self):
        schema = create_tool_schema(
            properties={"name": {"type": "string"}},
            required=["name"],
        )
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["required"] == ["name"]

    def test_with_description(self):
        schema = create_tool_schema(
            properties={},
            description="A test schema",
        )
        assert schema["description"] == "A test schema"

    def test_empty_required(self):
        schema = create_tool_schema(properties={"x": {"type": "integer"}})
        assert schema["required"] == []


class TestFunctionTool:

    def test_sync_handler(self):
        def add(x, y):
            return {"sum": x + y}

        tool = FunctionTool(
            name="add",
            description="Add two numbers",
            parameters=create_tool_schema(
                properties={"x": {"type": "integer"}, "y": {"type": "integer"}},
                required=["x", "y"],
            ),
            handler=add,
        )
        assert tool.name == "add"
        assert tool.description == "Add two numbers"
        assert tool.category == "general"

    @pytest.mark.asyncio
    async def test_execute_async_handler(self):
        async def greet(name):
            return {"content": [{"type": "text", "text": f"Hello {name}"}], "details": {"name": name}}

        tool = FunctionTool(
            name="greet",
            description="Greet someone",
            parameters=create_tool_schema(
                properties={"name": {"type": "string"}},
                required=["name"],
            ),
            handler=greet,
        )
        result = await tool.execute(name="World")
        assert result == {"content": [{"type": "text", "text": "Hello World"}], "details": {"name": "World"}}

    @pytest.mark.asyncio
    async def test_execute_sync_handler(self):
        def double(n):
            return {"result": n * 2}

        tool = FunctionTool(
            name="double",
            description="Double a number",
            parameters=create_tool_schema(
                properties={"n": {"type": "integer"}},
                required=["n"],
            ),
            handler=double,
        )
        result = await tool.execute(n=5)
        assert result == {"result": 10}

    def test_to_openai_schema(self):
        tool = FunctionTool(
            name="test",
            description="A test tool",
            parameters=create_tool_schema(properties={}),
            handler=lambda: None,
        )
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test"
        assert schema["function"]["description"] == "A test tool"


class TestToolWrapper:

    @pytest.mark.asyncio
    async def test_wrapper_preserves_pi_tool_result(self):
        async def handler(x):
            return {"content": [{"type": "text", "text": x}], "details": {"value": x}, "isError": False}

        tool = FunctionTool(
            name="wrap_test",
            description="test",
            parameters=create_tool_schema(properties={"x": {"type": "string"}}),
            handler=handler,
        )
        wrapper = ToolWrapper(tool)
        assert wrapper.name == "wrap_test"
        result = await wrapper(x="hello")
        assert result == {"content": [{"type": "text", "text": "hello"}], "details": {"value": "hello"}, "isError": False}

    @pytest.mark.asyncio
    async def test_wrapper_handles_exception(self):
        async def bad_handler():
            raise RuntimeError("boom")

        tool = FunctionTool(
            name="bad",
            description="test",
            parameters=create_tool_schema(properties={}),
            handler=bad_handler,
        )
        wrapper = ToolWrapper(tool)
        result = await wrapper()
        assert result["isError"] is True
        assert "boom" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_wrapper_dict_passthrough(self):
        async def handler():
            return {"custom": "result"}

        tool = FunctionTool(
            name="dict_test",
            description="test",
            parameters=create_tool_schema(properties={}),
            handler=handler,
        )
        wrapper = ToolWrapper(tool)
        result = await wrapper()
        assert result == {"custom": "result"}

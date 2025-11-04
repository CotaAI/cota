import logging
import asyncio
import json
from typing import Dict, Text, Tuple, Any, Optional, List
from .base import Executor
from cota.llm import LLM

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning(
        "MCP SDK not available. Please install it with: pip install mcp"
    )


class MCPClientWrapper:
    """MCP客户端包装类，管理MCP服务器连接和工具调用"""
    
    def __init__(self, server_params: StdioServerParameters):
        """
        初始化MCP客户端包装器
        
        Args:
            server_params: MCP服务器参数
        """
        self.server_params = server_params
        self._stdio_context = None
        self._read = None
        self._write = None
        self._session: Optional[ClientSession] = None
        self._initialized = False
        
    async def ensure_connected(self) -> ClientSession:
        """确保MCP连接已建立并初始化"""
        if not self._initialized or self._session is None:
            try:
                # 创建stdio客户端上下文管理器
                self._stdio_context = stdio_client(self.server_params)
                self._read, self._write = await self._stdio_context.__aenter__()
                
                # 创建会话
                self._session = ClientSession(self._read, self._write)
                
                # 初始化会话
                await self._session.initialize()
                self._initialized = True
                logger.info("MCP会话初始化成功")
                
            except Exception as e:
                logger.error(f"MCP连接失败: {e}")
                self._initialized = False
                raise
        
        return self._session
    
    async def list_tools(self) -> List[Dict]:
        """列出所有可用的工具"""
        session = await self.ensure_connected()
        try:
            result = await session.list_tools()
            tools = []
            for tool in result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                })
            return tools
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")
            raise
    
    async def list_prompts(self) -> List[Dict]:
        """列出所有可用的prompts"""
        session = await self.ensure_connected()
        try:
            result = await session.list_prompts()
            prompts = []
            for prompt in result.prompts:
                prompts.append({
                    "name": prompt.name,
                    "description": prompt.description or "",
                    "arguments": prompt.arguments if hasattr(prompt, 'arguments') else []
                })
            return prompts
        except Exception as e:
            logger.error(f"获取prompts列表失败: {e}")
            raise
    
    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """调用MCP工具"""
        session = await self.ensure_connected()
        try:
            result = await session.call_tool(tool_name, arguments)
            return {
                "content": result.content if hasattr(result, 'content') else [],
                "isError": result.isError if hasattr(result, 'isError') else False
            }
        except Exception as e:
            logger.error(f"调用工具 {tool_name} 失败: {e}")
            raise
    
    async def get_prompt(self, prompt_name: str, arguments: Optional[Dict] = None) -> Dict:
        """获取MCP prompt"""
        session = await self.ensure_connected()
        try:
            result = await session.get_prompt(prompt_name, arguments or {})
            return {
                "messages": result.messages if hasattr(result, 'messages') else [],
                "description": result.description if hasattr(result, 'description') else ""
            }
        except Exception as e:
            logger.error(f"获取prompt {prompt_name} 失败: {e}")
            raise
    
    async def close(self):
        """关闭连接"""
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
                self._session = None
            
            if self._stdio_context:
                await self._stdio_context.__aexit__(None, None, None)
                self._stdio_context = None
            
            self._read = None
            self._write = None
            self._initialized = False
            logger.info("MCP连接已关闭")
        except Exception as e:
            logger.error(f"关闭MCP连接时出错: {e}")


class MCPExecutor(Executor):
    """MCP (Model Context Protocol) executor
    
    Supports communication with local MCP servers via stdio using the official MCP SDK.
    Maintains its own LLM instance for interacting with MCP server and supports
    custom prompts for better business results.
    """
    
    def __init__(self, config: Dict[Text, Any]) -> None:
        super().__init__(config)
        
        if not MCP_AVAILABLE:
            raise ImportError(
                "MCP SDK is required. Please install it with: pip install mcp"
            )
        
        # Initialize LLM instance from config
        llm_config = self.config.get("llm", {})
        if not llm_config:
            raise ValueError("LLM configuration is required for MCP executor")
        
        self.llm = LLM(llm_config)
        logger.info(f"Initialized LLM for MCP executor: {llm_config.get('model', 'unknown')}")
        
        # MCP server configuration
        self.server_command = self.config.get("server_command", [])
        if not self.server_command:
            raise ValueError("MCP server_command is required (list of command and args)")
        
        self.custom_prompt = self.config.get("prompt", None)
        self.max_tokens = self.config.get("max_tokens", 500)
        
        # Create MCP client wrapper
        server_params = StdioServerParameters(
            command=self.server_command[0],
            args=self.server_command[1:] if len(self.server_command) > 1 else []
        )
        self._mcp_client: Optional[MCPClientWrapper] = MCPClientWrapper(server_params)
    
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute MCP operation
        
        The executor uses LLM to determine how to interact with MCP server based on:
        1. Available tools/prompts from MCP server
        2. Custom prompt (if configured)
        3. Input data
        
        Args:
            data: Data required for execution (form slots, etc.)
            
        Returns:
            Tuple[Response text, Metadata]
        """
        try:
            # Step 1: Get available tools and prompts from MCP server
            tools = await self._mcp_client.list_tools()
            prompts = await self._mcp_client.list_prompts()
            
            # Step 2: Analyze if tools/prompts are needed using LLM
            needs_tools = await self._analyze_need_for_tools(data, tools, prompts)
            
            if not needs_tools.get("needs_tools", False):
                # If no tools needed, use LLM directly
                direct_response = await self._get_direct_llm_response(data)
                return direct_response, {"mcp_action": "direct_response", "reasoning": needs_tools.get("reasoning", "")}
            
            # Step 3: Use LLM to select appropriate tool/prompt and generate arguments
            action = await self._select_tool_or_prompt(data, tools, prompts, needs_tools)
            
            # Step 4: Execute action on MCP server
            result_text = ""
            metadata = {
                "mcp_action": action.get("type"),
                "selection_reasoning": action.get("reasoning", "")
            }
            
            try:
                if action.get("type") == "call_tool":
                    tool_name = action.get("tool_name")
                    tool_args = action.get("arguments", {})
                    tool_result = await self._mcp_client.call_tool(tool_name, tool_args)
                    
                    # Extract text from content array
                    content_items = tool_result.get("content", [])
                    if content_items:
                        text_parts = []
                        for item in content_items:
                            if isinstance(item, dict):
                                text_parts.append(item.get("text", str(item)))
                            else:
                                text_parts.append(str(item))
                        result_text = "\n".join(text_parts)
                    else:
                        result_text = str(tool_result)
                    
                    metadata["tool_result"] = tool_result
                    
                    # Step 5: Use LLM to integrate tool result and generate final response
                    final_response = await self._generate_final_response(data, tool_result, result_text)
                    return final_response, metadata
                    
                elif action.get("type") == "get_prompt":
                    prompt_name = action.get("prompt_name")
                    prompt_args = action.get("arguments", {})
                    prompt_result = await self._mcp_client.get_prompt(prompt_name, prompt_args)
                    
                    # Extract text from messages
                    messages = prompt_result.get("messages", [])
                    if messages:
                        text_parts = []
                        for msg in messages:
                            if isinstance(msg, dict):
                                text_parts.append(msg.get("content", {}).get("text", str(msg)))
                            else:
                                text_parts.append(str(msg))
                        result_text = "\n".join(text_parts)
                    else:
                        result_text = prompt_result.get("description", str(prompt_result))
                    
                    metadata["prompt_result"] = prompt_result
                    return result_text, metadata
                    
                else:
                    # Fallback to direct LLM response
                    direct_response = await self._get_direct_llm_response(data)
                    return direct_response, metadata
                    
            except Exception as tool_error:
                # If tool execution fails, fallback to direct LLM response
                logger.warning(f"Tool execution failed, falling back to direct LLM: {tool_error}")
                direct_response = await self._get_direct_llm_response(data)
                metadata["tool_error"] = str(tool_error)
                return direct_response, metadata
            
        except Exception as e:
            error_msg = f"Failed to execute MCP operation: {str(e)}"
            logger.error(error_msg, exc_info=True)
            # Final fallback: try to get direct LLM response
            try:
                direct_response = await self._get_direct_llm_response(data)
                return direct_response, {"error": error_msg, "fallback": True}
            except:
                return "", {"error": error_msg}
    
    async def _analyze_need_for_tools(self, data: Dict, tools: List[Dict], prompts: List[Dict]) -> Dict:
        """使用LLM分析是否需要调用工具"""
        analysis_prompt = f"""分析以下用户输入，判断是否需要调用外部工具或服务。

用户输入数据:
{json.dumps(data, indent=2, ensure_ascii=False)}

可用工具列表: {[tool.get('name') for tool in tools]}
可用Prompts列表: {[prompt.get('name') for prompt in prompts]}

请分析：
1. 这个输入是否需要实时数据、计算或外部服务？
2. 如果需要，应该调用什么类型的工具或prompt？
3. 请用JSON格式返回分析结果，包含以下字段：
   - needs_tools: boolean (是否需要工具)
   - tool_type: string (工具类型，如calculator, weather, database等)
   - reasoning: string (分析理由)

如果不需要工具，返回：
{{"needs_tools": false, "tool_type": "", "reasoning": "不需要工具的原因"}}
"""
        
        try:
            llm_response = await self.llm.generate_chat(
                messages=[{"role": "user", "content": analysis_prompt}],
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            analysis = json.loads(llm_response.get("content", "{}"))
            return analysis
        except Exception as e:
            logger.warning(f"分析工具需求失败，默认认为需要工具: {e}")
            return {"needs_tools": True, "tool_type": "unknown", "reasoning": f"分析失败: {str(e)}"}
    
    async def _select_tool_or_prompt(self, data: Dict, tools: List[Dict], prompts: List[Dict], analysis: Dict) -> Dict:
        """使用LLM选择合适的工具和参数"""
        tools_info = "\n".join([
            f"- {tool.get('name')}: {tool.get('description', '')}"
            for tool in tools
        ])
        
        prompts_info = "\n".join([
            f"- {prompt.get('name')}: {prompt.get('description', '')}"
            for prompt in prompts
        ])
        
        selection_prompt = f"""基于以下信息，选择合适的工具或prompt并生成调用参数。

用户输入数据:
{json.dumps(data, indent=2, ensure_ascii=False)}

分析结果: {json.dumps(analysis, indent=2, ensure_ascii=False)}

可用工具:
{tools_info}

可用Prompts:
{prompts_info}

请返回JSON格式，包含：
{{
    "type": "call_tool" 或 "get_prompt",
    "tool_name": "选中的工具名称" 或 "prompt_name": "选中的prompt名称",
    "arguments": {{"参数名": "参数值"}},
    "reasoning": "选择理由"
}}

只返回JSON，不要其他内容。"""
        
        if self.custom_prompt:
            system_prompt = self.custom_prompt
        else:
            system_prompt = "你是一个智能助手，能够分析用户需求并选择合适的工具来完成任务。"
        
        try:
            llm_response = await self.llm.generate_chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": selection_prompt}
                ],
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )
            
            return self._parse_llm_response(llm_response.get("content", ""))
        except Exception as e:
            logger.error(f"选择工具失败: {e}")
            return {"type": "direct_response", "reasoning": f"选择失败: {str(e)}"}
    
    async def _generate_final_response(self, original_data: Dict, tool_result: Dict, tool_text: str) -> str:
        """使用LLM整合工具结果生成最终回答"""
        final_prompt = f"""基于工具调用结果，给用户一个完整、自然的回答。

用户原始输入:
{json.dumps(original_data, indent=2, ensure_ascii=False)}

工具调用结果:
{json.dumps(tool_result, indent=2, ensure_ascii=False)}

工具返回文本:
{tool_text}

请生成一个自然、完整的回答，直接回答用户的问题，不要重复说明调用了什么工具。"""
        
        try:
            llm_response = await self.llm.generate_chat(
                messages=[{"role": "user", "content": final_prompt}],
                max_tokens=self.max_tokens
            )
            return llm_response.get("content", tool_text)
        except Exception as e:
            logger.warning(f"生成最终回答失败，返回工具结果: {e}")
            return tool_text
    
    async def _get_direct_llm_response(self, data: Dict) -> str:
        """获取直接的LLM回答（不调用工具）"""
        user_input = json.dumps(data, indent=2, ensure_ascii=False)
        
        if self.custom_prompt:
            system_prompt = self.custom_prompt
        else:
            system_prompt = "你是一个有用的助手，请根据用户输入提供准确、有帮助的回答。"
        
        try:
            llm_response = await self.llm.generate_chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户输入:\n{user_input}\n\n请提供回答。"}
                ],
                max_tokens=self.max_tokens
            )
            return llm_response.get("content", "")
        except Exception as e:
            logger.error(f"直接LLM回答失败: {e}")
            return ""
    
    def _parse_llm_response(self, content: str) -> Dict:
        """Parse LLM response to extract action"""
        try:
            # Try to parse as JSON
            response = json.loads(content)
            return response
        except json.JSONDecodeError:
            # Try to extract JSON from string
            try:
                import re
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    response = json.loads(json_match.group())
                    return response
            except:
                pass
            
            # If all else fails, return direct response
            logger.warning(f"Failed to parse LLM response as JSON, using as direct response: {content}")
            return {
                "type": "direct_response",
                "content": content
            }
    
    async def cleanup(self) -> None:
        """Clean up MCP server resources"""
        if self._mcp_client:
            await self._mcp_client.close()
            self._mcp_client = None
        logger.info("MCP executor cleaned up")


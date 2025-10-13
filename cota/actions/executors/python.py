import logging
import asyncio
from typing import Dict, Text, Tuple, Any
from .base import Executor

logger = logging.getLogger(__name__)

class PythonExecutor(Executor):
    """Python executor
    
    Handles Python code execution logic. Supports both synchronous and asynchronous code execution.
    """
    
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute Python code
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        code = self.config.get("code", "")
        if not code:
            return "", {"error": "No code provided"}
            
        try:
            # Create local namespace
            namespace = {
                "data": data,
                "config": self.config,
                "result": {"text": "", "metadata": {}}
            }
            
            # Check if code is an async function
            is_async = "async def" in code
            
            if is_async:
                # If it's async code, use exec to compile and execute
                exec_code = f"""
async def _execute():
    {code}
"""
                exec(exec_code, namespace)
                await namespace["_execute"]()
            else:
                # If it's sync code, execute directly
                exec(code, namespace)
            
            result = namespace.get("result", {})
            return result.get("text", ""), result.get("metadata", {})
            
        except Exception as e:
            logger.error(f"Failed to execute Python code: {str(e)}")
            return "", {"error": str(e)} 
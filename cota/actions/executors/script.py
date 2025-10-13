import logging
import asyncio
import json
from typing import Dict, Text, Tuple, Any
from .base import Executor

logger = logging.getLogger(__name__)

class ScriptExecutor(Executor):
    """Script executor
    
    Handles execution logic for external scripts. Supports executing shell scripts or other executable files.
    """
    
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute external script
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        script_path = self.config.get("script_path", "")
        if not script_path:
            return "", {"error": "No script path provided"}
            
        try:
            # Prepare command line arguments
            args = self.config.get("args", [])
            
            # Convert data to JSON string as argument
            data_arg = json.dumps(data)
            command = [script_path] + args + [data_arg]
            
            # Create subprocess
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for execution completion
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Script execution failed: {error_msg}")
                return "", {"error": error_msg}
                
            # Try to parse output as JSON format
            try:
                output = stdout.decode().strip()
                result = json.loads(output)
                return result.get("text", ""), result.get("metadata", {})
            except json.JSONDecodeError:
                # If cannot parse as JSON, return output text directly
                return stdout.decode().strip(), {}
                
        except Exception as e:
            logger.error(f"Failed to execute script: {str(e)}")
            return "", {"error": str(e)} 
import logging
from typing import Dict, Text, Tuple, Any
from .base import Executor
from cota.utils.http import HttpClientManager

logger = logging.getLogger(__name__)

class HttpExecutor(Executor):
    """HTTP executor
    
    Handles execution logic based on HTTP requests.
    """
    
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute HTTP request
        
        Args:
            data: Request data
            
        Returns:
            Tuple[Response text, Metadata]
        """
        url = self.config.get("url", "")
        method = self.config.get("method", "get").upper()
        
        try:
            # Get HTTP client
            client = await HttpClientManager.instance().get_client(
                self.config.get("client_key", "default")
            )
            
            # Execute request
            if method == "GET":
                response = await client.get(url, params=data)
            else:
                response = await client.request(method, url, json_data=data)
            
            if not response.ok:
                raise Exception(f"Request failed with status {response.status}")
                
            return response.data.get("text", ""), response.data.get("metadata", {})
        except Exception as e:
            logger.error(f"Failed to execute HTTP request: {str(e)}")
            return "", {"error": str(e)} 
import logging
from typing import Optional, Dict
from .client import HttpClient, HttpConfig

logger = logging.getLogger(__name__)

class HttpClientManager:
    """HTTP client manager
    
    Unified management of HTTP client instances, implementing client reuse and lifecycle management
    """
    _instance = None
    _clients: Dict[str, HttpClient] = {}
    
    def __init__(self):
        if HttpClientManager._instance is not None:
            raise RuntimeError("HttpClientManager is a singleton!")
        HttpClientManager._instance = self
    
    @classmethod
    def instance(cls) -> 'HttpClientManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def get_client(self, config_key: str = "default", config: Optional[HttpConfig] = None) -> HttpClient:
        """Get or create HTTP client
        
        Args:
            config_key: Configuration key, used to reuse clients with same configuration
            config: HTTP client configuration, create new client if not exists
            
        Returns:
            HttpClient instance
        """
        if config_key not in self._clients:
            client = HttpClient(config or HttpConfig())
            await client.connect()
            self._clients[config_key] = client
            
        return self._clients[config_key]
    
    async def close_all(self):
        """Close all client connections"""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
    
    async def close_client(self, config_key: str):
        """Close specified client connection"""
        if config_key in self._clients:
            await self._clients[config_key].close()
            del self._clients[config_key] 
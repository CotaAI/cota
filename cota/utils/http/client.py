import logging
import asyncio
import aiohttp
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from aiohttp import ClientTimeout

logger = logging.getLogger(__name__)

@dataclass
class HttpConfig:
    """HTTP client configuration"""
    max_retries: int = 3
    timeout: int = 300  # 5 minutes
    base_url: str = ""
    default_headers: Dict[str, str] = None
    
    def __post_init__(self):
        if self.default_headers is None:
            self.default_headers = {"Content-Type": "application/json"}

class HttpResponse:
    """HTTP response wrapper"""
    def __init__(self, status: int, data: Any, headers: Dict[str, str]):
        self.status = status
        self.data = data
        self.headers = headers
        
    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

class HttpClient:
    """HTTP client implementation
    
    Provides configurable HTTP client implementation, supports:
    - Automatic retry
    - Timeout control
    - Unified error handling
    - Request/response interception
    """
    
    def __init__(self, config: Optional[HttpConfig] = None):
        self.config = config or HttpConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    async def connect(self):
        """Create connection session"""
        if not self._session:
            timeout = ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
            
    async def close(self):
        """Close connection session"""
        if self._session:
            await self._session.close()
            self._session = None
    
    def _build_url(self, path: str) -> str:
        """Build complete request URL"""
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
    
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        **kwargs
    ) -> HttpResponse:
        """Send HTTP request
        
        Args:
            method: HTTP method
            url: Request path or complete URL
            params: URL query parameters
            json_data: JSON request body
            headers: Request headers
            **kwargs: Other parameters supported by aiohttp
            
        Returns:
            HttpResponse object
            
        Raises:
            Exception: Thrown when still fails after retries
        """
        if not self._session:
            await self.connect()
            
        merged_headers = {**self.config.default_headers, **(headers or {})}
        full_url = self._build_url(url)
        last_error = None
        
        for attempt in range(self.config.max_retries):
            try:
                async with self._session.request(
                    method,
                    full_url,
                    params=params,
                    json=json_data,
                    headers=merged_headers,
                    **kwargs
                ) as response:
                    data = await response.json()
                    return HttpResponse(
                        status=response.status,
                        data=data,
                        headers=dict(response.headers)
                    )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"HTTP request attempt {attempt + 1} failed: {str(e)}",
                    extra={
                        "url": full_url,
                        "method": method,
                        "attempt": attempt + 1
                    }
                )
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                continue
                
        raise Exception(
            f"HTTP request failed after {self.config.max_retries} attempts: {str(last_error)}"
        )
    
    async def get(self, url: str, **kwargs) -> HttpResponse:
        """Send GET request"""
        return await self.request("GET", url, **kwargs)
        
    async def post(self, url: str, **kwargs) -> HttpResponse:
        """Send POST request"""
        return await self.request("POST", url, **kwargs)
        
    async def put(self, url: str, **kwargs) -> HttpResponse:
        """Send PUT request"""
        return await self.request("PUT", url, **kwargs)
        
    async def delete(self, url: str, **kwargs) -> HttpResponse:
        """Send DELETE request"""
        return await self.request("DELETE", url, **kwargs) 
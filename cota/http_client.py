import logging
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class HttpClient:
    """Encapsulate HTTP request logic"""
    
    def __init__(self, max_retries: int = 3, timeout: int = 10):
        self.max_retries = max_retries
        self.timeout = timeout
        
    async def request(self, method: str, url: str, headers: Optional[Dict] = None, 
                     params: Optional[Dict] = None, json_data: Optional[Dict] = None):
        headers = headers or {"Content-Type": "application/json"}
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    if method.lower() == "get":
                        async with session.get(
                            url, 
                            headers=headers, 
                            params=params,
                            timeout=self.timeout
                        ) as response:
                            response.raise_for_status()
                            return await response.json()
                    else:
                        async with session.request(
                            method, 
                            url, 
                            headers=headers, 
                            json=json_data,
                            timeout=self.timeout
                        ) as response:
                            response.raise_for_status()
                            return await response.json()
            except Exception as e:
                last_error = e
                logger.warning(f"HTTP request attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                continue
                
        raise Exception(f"HTTP request failed after {self.max_retries} attempts: {str(last_error)}") 
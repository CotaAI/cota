import asyncio
import time
from typing import Any, Dict, Optional

class ConnectionPool:
    """Generic connection pool for managing WebSocket/SSE connections"""
    def __init__(self):
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "peak_connections": 0,
            "connection_errors": 0
        }
    
    async def add(self, user_id: str, connection: Any) -> bool:
        """Add a new connection to the pool
        
        Args:
            user_id: Unique identifier for the user
            connection: WebSocket/SSE connection object
        """
        user_id = str(user_id)
        async with self._lock:
            self._connections[user_id] = {
                "connection": connection,
                "connected_at": time.time(),
                "last_activity": time.time(),
                "metadata": {}
            }
            self._stats["total_connections"] += 1
            self._stats["active_connections"] = len(self._connections)
            self._stats["peak_connections"] = max(
                self._stats["peak_connections"], 
                self._stats["active_connections"]
            )
            logger.debug(f"Added connection for {user_id}, active: {self._stats['active_connections']}")
            return True
    
    async def remove(self, user_id: str) -> bool:
        """Remove a connection from the pool"""
        user_id = str(user_id)
        async with self._lock:
            if user_id in self._connections:
                del self._connections[user_id]
                self._stats["active_connections"] = len(self._connections)
                logger.debug(f"Removed connection for {user_id}, active: {self._stats['active_connections']}")
                return True
            return False
    
    async def get(self, user_id: str) -> Optional[Any]:
        """Retrieve the connection for a user"""
        user_id = str(user_id)
        async with self._lock:
            conn_data = self._connections.get(user_id)
            if conn_data:
                conn_data["last_activity"] = time.time()
                return conn_data["connection"]
            return None
    
    async def update_activity(self, user_id: str) -> bool:
        """Update last activity timestamp for a connection"""
        user_id = str(user_id)
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id]["last_activity"] = time.time()
                return True
            return False
    
    async def get_all_connections(self) -> Dict[str, Any]:
        """Get all active connections"""
        result = {}
        async with self._lock:
            for user_id, conn_data in self._connections.items():
                result[user_id] = conn_data["connection"]
        return result
    
    async def get_stats(self) -> Dict[str, int]:
        """Get connection pool statistics"""
        async with self._lock:
            return dict(self._stats)
    
    async def cleanup_inactive(self, timeout: int = 3000) -> int:
        """Clean up inactive connections
        
        Args:
            timeout: Inactivity timeout in seconds
            
        Returns:
            Number of connections cleaned up
        """
        now = time.time()
        to_remove = []
        
        async with self._lock:
            for user_id, conn_data in self._connections.items():
                if now - conn_data["last_activity"] > timeout:
                    to_remove.append(user_id)
        
        count = 0
        for user_id in to_remove:
            conn = await self.get(user_id)
            if conn:
                try:
                    # Handle both WebSocket and SSE connections
                    if hasattr(conn, 'close'):
                        await conn.close(1000, "Connection timeout")
                    count += 1
                except Exception as e:
                    logger.error(f"Error closing inactive connection for {user_id}: {e}")
                    self._stats["connection_errors"] += 1
                finally:
                    await self.remove(user_id)
        
        return count
    
    def __len__(self) -> int:
        """Get total number of active connections"""
        return len(self._connections)
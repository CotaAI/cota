import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

class RoomManager:

    def __init__(self):
        self._rooms: Dict[str, Dict[str, Any]] = {}
        self._user_rooms: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()
    
    async def create_or_update_room(self, room_id: str, user_ids: List[str]) -> bool:
        room_id = str(room_id)
        user_ids = [str(uid) for uid in user_ids]
        
        async with self._lock:
            self._rooms[room_id] = {
                "user_ids": user_ids,
                "created_at": self._rooms.get(room_id, {}).get("created_at", time.time()),
                "updated_at": time.time(),
                "last_activity": time.time()
            }
            
            # Update user-room map
            for user_id in user_ids:
                if user_id not in self._user_rooms:
                    self._user_rooms[user_id] = set()
                self._user_rooms[user_id].add(room_id)
            
            # Iterate through all users that currently have room associations
            # We use list() to create a static copy for safe iteration while modifying
            for user_id in list(self._user_rooms.keys()):
                # Check if the user is not in the updated room member list but still has this room association
                if user_id not in user_ids and room_id in self._user_rooms[user_id]:
                    # Remove this room from the user's room set
                    self._user_rooms[user_id].remove(room_id)
                    
                    # If the user has no remaining room associations after removal
                    if not self._user_rooms[user_id]:
                        # Delete the user entry entirely to prevent empty sets and maintain memory efficiency
                        del self._user_rooms[user_id]
            
            logger.debug(f"Updated room {room_id} with users: {user_ids}")
            return True
    
    async def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        room_id = str(room_id)
        async with self._lock:
            room = self._rooms.get(room_id)
            if room:
                room["last_activity"] = time.time()
            return room
    
    async def get_room_users(self, room_id: str) -> List[str]:
        room_id = str(room_id)
        async with self._lock:
            room = self._rooms.get(room_id)
            return room["user_ids"] if room else []
    
    async def get_user_rooms(self, user_id: str) -> List[str]:
        user_id = str(user_id)
        async with self._lock:
            return list(self._user_rooms.get(user_id, set()))
    
    async def remove_room(self, room_id: str) -> bool:
        room_id = str(room_id)
        async with self._lock:
            if room_id in self._rooms:
                user_ids = self._rooms[room_id]["user_ids"]
                del self._rooms[room_id]
                
                # Update user-room map
                for user_id in user_ids:
                    if user_id in self._user_rooms:
                        self._user_rooms[user_id].discard(room_id)
                        if not self._user_rooms[user_id]:
                            del self._user_rooms[user_id]
                
                logger.debug(f"Removed room {room_id}")
                return True
            return False
    
    async def cleanup_inactive(self, timeout: int = 3600) -> int:
        now = time.time()
        to_remove = []
        
        async with self._lock:
            for room_id, room in self._rooms.items():
                if now - room["last_activity"] > timeout:
                    to_remove.append(room_id)
        
        count = 0
        for room_id in to_remove:
            if await self.remove_room(room_id):
                count += 1
        
        return count

    async def add_user_to_room(self, room_id: str, user_id: str) -> None:
        """Add a user to a room"""
        room = await self.get_or_create_room(room_id)
        if user_id not in room["user_ids"]:
            room["user_ids"].append(user_id)
            room["updated_at"] = time.time()
            room["last_activity"] = time.time()
            
            # Update user-room map
            if user_id not in self._user_rooms:
                self._user_rooms[user_id] = set()
            self._user_rooms[user_id].add(room_id)
            
            # Iterate through all users that currently have room associations
            # We use list() to create a static copy for safe iteration while modifying
            for user_id in list(self._user_rooms.keys()):
                # Check if the user is not in the updated room member list but still has this room association
                if user_id not in room["user_ids"] and room_id in self._user_rooms[user_id]:
                    # Remove this room from the user's room set
                    self._user_rooms[user_id].remove(room_id)
                    
                    # If the user has no remaining room associations after removal
                    if not self._user_rooms[user_id]:
                        # Delete the user entry entirely to prevent empty sets and maintain memory efficiency
                        del self._user_rooms[user_id]
            
            logger.debug(f"Updated room {room_id} with users: {room['user_ids']}")
    
    async def remove_user_from_room(self, room_id: str, user_id: str) -> None:
        """Remove a user from a room"""
        room = await self.get_room(room_id)
        if room and user_id in room["user_ids"]:
            room["user_ids"].remove(user_id)
            room["updated_at"] = time.time()
            room["last_activity"] = time.time()
            
            # If the room is empty, delete the room
            if not room["user_ids"]:
                await self.remove_room(room_id)
            
            # Update user-room map
            if user_id in self._user_rooms:
                self._user_rooms[user_id].discard(room_id)
                if not self._user_rooms[user_id]:
                    del self._user_rooms[user_id]
            
            logger.debug(f"Updated room {room_id} with users: {room['user_ids']}")
    
    async def get_or_create_room(self, room_id: str) -> Dict[str, Any]:
        """Get or create a room"""
        room = await self.get_room(room_id)
        if room is None:
            room = {
                "user_ids": [],
                "created_at": time.time(),
                "updated_at": time.time(),
                "last_activity": time.time()
            }
            self._rooms[room_id] = room
        return room
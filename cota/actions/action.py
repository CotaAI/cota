import time
from typing import Text, Optional, Any, Dict, List

registry = []


class Action:
    def __init__(
            self,
            name: Optional[Text] = None,
            description: Optional[Text] = None,
            prompt: Optional[Text] = None,
            llm: Optional[Text] = None,
            timestamp: Optional[float] = None,
            sender_id: Optional[Text] = None,
            receiver_id: Optional[Text] = None,
            result: Optional[List] = None
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt
        self.llm = llm
        self.timestamp = timestamp or time.time()
        self.sender_id = sender_id or 'default_sender'
        self.receiver_id = receiver_id or 'default_receiver'
        self.result = result or list()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registry.append(cls)

    @staticmethod
    def resolve_by_type(
            name: Text
    ) -> "Action":
        # Try exact match first
        for cls in registry:
            if cls.__name__ == name:
                return cls
        
        # Try case-insensitive match
        name_lower = name.lower()
        for cls in registry:
            if cls.__name__.lower() == name_lower:
                return cls
        
        # if not in register
        new_class = type(name, (Action,), {})
        new_class.__name__ = name
        return new_class


    def apply_to(self,dst) -> None:
        dst.actions.append(self)
        dst.latest_action = self

    @staticmethod
    def build_from_name(**kwargs) -> "Action":
        action_class = Action.resolve_by_type(kwargs.get("name"))
        if not action_class:
            return None
        return action_class(**kwargs)

    def run_from_dict(
            self,
            action_dict
    ) -> None:
        self.name = action_dict.get("name") or self.name
        self.timestamp = action_dict.get("timestamp") or self.timestamp
        self.sender_id = action_dict.get("sender_id") or self.sender_id
        self.receiver_id = action_dict.get("receiver_id") or self.receiver_id
        self.result = action_dict.get("result")

    def run_from_string(
            self,
            text
    ) -> None:
        """Implementation based on string"""
        raise NotImplementedError

    async def run(self, agent, dst) -> None:
        raise NotImplementedError

    def as_dict(self) -> Dict[Text, Any]:
        d = {
            "name": self.__class__.__name__,
            "timestamp": self.timestamp,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id
        }
        if self.result:
            d["result"] = self.result
        return d
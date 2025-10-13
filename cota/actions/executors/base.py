from typing import Dict, Text, Tuple, Any
from abc import ABC, abstractmethod

class Executor(ABC):
    """Base executor class
    
    Defines the basic interface for executors, all concrete executors should inherit from this class.
    """
    
    def __init__(self, config: Dict[Text, Any]) -> None:
        self.config = config
    
    @abstractmethod
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute specific operation
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        pass
    
    async def cleanup(self) -> None:
        """Clean up resources
        
        Subclasses can override this method to implement resource cleanup logic.
        """
        pass
    
    @classmethod
    def create(cls, executor_type: Text, config: Dict[Text, Any]) -> "Executor":
        """Create executor instance
        
        Args:
            executor_type: Executor type
            config: Executor configuration
            
        Returns:
            Executor: Executor instance
        """
        from .http import HttpExecutor
        from .script import ScriptExecutor
        from .python import PythonExecutor
        from .plugin import PluginExecutor
        
        executor_map = {
            "http": HttpExecutor,
            "script": ScriptExecutor,
            "python": PythonExecutor,
            "plugin": PluginExecutor
        }
        
        executor_class = executor_map.get(executor_type)
        if not executor_class:
            raise ValueError(f"Unknown executor type: {executor_type}")
            
        # Remove type information as it has been used
        config = config.copy()
        config.pop("type", None)
            
        return executor_class(config) 
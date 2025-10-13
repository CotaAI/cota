from abc import ABC, abstractmethod
from typing import Dict, Text, Tuple, Any

class BasePlugin(ABC):
    """Plugin base class
    
    All user-defined plugins should inherit from this class and implement necessary methods.
    """
    
    def __init__(self, config: Dict[Text, Any]) -> None:
        """Initialize plugin
        
        Args:
            config: Plugin configuration
        """
        self.config = config
        
    @abstractmethod
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute plugin logic
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        pass
        
    async def cleanup(self) -> None:
        """Clean up plugin resources
        
        If plugin needs to clean up resources when closing, can override this method.
        """
        pass 
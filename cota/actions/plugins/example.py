from typing import Dict, Text, Tuple, Any
from .base import BasePlugin

class Plugin(BasePlugin):
    """Example plugin
    
    Demonstrates how to implement a custom plugin. This plugin implements a simple text processing function.
    """
    
    def __init__(self, config: Dict[Text, Any]) -> None:
        super().__init__(config)
        self.prefix = config.get("prefix", "")
        self.suffix = config.get("suffix", "")
        
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute plugin logic
        
        This example plugin adds prefix and suffix to input text.
        
        Args:
            data: Data dictionary containing "text" field
            
        Returns:
            Tuple[Processed text, Metadata]
        """
        input_text = data.get("text", "")
        processed_text = f"{self.prefix}{input_text}{self.suffix}"
        
        metadata = {
            "original_length": len(input_text),
            "processed_length": len(processed_text),
            "prefix_used": self.prefix,
            "suffix_used": self.suffix
        }
        
        return processed_text, metadata 
import logging
import importlib.util
import os
from typing import Dict, Text, Tuple, Any, Optional, Callable
from .base import Executor

logger = logging.getLogger(__name__)

class PluginExecutor(Executor):
    """Plugin executor
    
    Supports loading and executing user-defined plugins. Plugin is a Python module that needs to implement specific interfaces.
    """
    
    def __init__(self, config: Dict[Text, Any]) -> None:
        super().__init__(config)
        # Get plugin configuration
        self.plugin_path = self._get_plugin_path()
        self.plugin_name = config.get("plugin_name", "")
        self._plugin_module = None
        self._plugin_instance = None
        self._load_plugin()
        
    def _get_plugin_path(self) -> Text:
        """Get plugin path
        
        Prioritize using path from configuration, if none then use default path.
        
        Returns:
            Text: Plugin path
        """
        # First try to use path from configuration
        plugin_path = self.config.get("plugin_path", "")
        if plugin_path:
            return plugin_path
            
        # If not configured, use default path
        # Default path is cota/actions/plugins
        import cota
        base_path = os.path.dirname(os.path.dirname(cota.__file__))
        return os.path.join(base_path, "actions", "plugins")
        
    def _load_plugin(self) -> None:
        """Load plugin module"""
        try:
            if not self.plugin_name:
                raise ValueError("Plugin name must be provided")
                
            # Build complete plugin path
            full_path = os.path.join(self.plugin_path, f"{self.plugin_name}.py")
            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Plugin file not found: {full_path}")
                
            # Load plugin module
            spec = importlib.util.spec_from_file_location(self.plugin_name, full_path)
            if not spec or not spec.loader:
                raise ImportError(f"Failed to load plugin spec: {self.plugin_name}")
                
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._plugin_module = module
            
            # Validate plugin interface
            if not hasattr(module, "Plugin"):
                raise AttributeError(f"Plugin class not found in module: {self.plugin_name}")
                
            plugin_class = getattr(module, "Plugin")
            self._plugin_instance = plugin_class(self.config)
            
            # Validate required methods
            if not hasattr(self._plugin_instance, "execute") or not callable(getattr(self._plugin_instance, "execute")):
                raise AttributeError(f"Plugin must implement 'execute' method: {self.plugin_name}")
                
            logger.info(f"Successfully loaded plugin: {self.plugin_name} from {full_path}")
            
        except Exception as e:
            logger.error(f"Failed to load plugin {self.plugin_name}: {str(e)}")
            raise
            
    async def execute(self, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute plugin
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        if not self._plugin_instance:
            return "", {"error": "Plugin not loaded"}
            
        try:
            return await self._plugin_instance.execute(data)
        except Exception as e:
            error_msg = f"Failed to execute plugin {self.plugin_name}: {str(e)}"
            logger.error(error_msg)
            return "", {"error": error_msg}
            
    async def cleanup(self) -> None:
        """Clean up plugin resources"""
        if self._plugin_instance and hasattr(self._plugin_instance, "cleanup"):
            try:
                await self._plugin_instance.cleanup()
            except Exception as e:
                logger.error(f"Failed to cleanup plugin {self.plugin_name}: {str(e)}")
                
        # Clean up module references
        self._plugin_module = None
        self._plugin_instance = None 
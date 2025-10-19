import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Text, List, Union, Optional, Dict, Any

logger = logging.getLogger(__name__)


class Knowledge(ABC):
    """Base class for knowledge retrieval systems."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
    
    @abstractmethod
    async def retrieve(self, query: str, context: Dict[str, Any] = None) -> str:
        """Retrieve knowledge based on query and context.
        
        Args:
            query: The search query
            context: Additional context information (DST, action, etc.)
            
        Returns:
            Retrieved knowledge as string
        """
        pass
    
    async def process_query(self, query: str, context: Dict[str, Any] = None) -> str:
        """Process query and return formatted result."""
        try:
            result = await self.retrieve(query, context)
            return self._format_result(result)
        except Exception as e:
            logger.error(f"Knowledge retrieval failed: {e}")
            return ""
    
    def _format_result(self, result: str) -> str:
        """Format the retrieval result."""
        return result.strip() if result else ""


class CompositeKnowledge(Knowledge):
    """
    Composite Knowledge - manages multiple Knowledge strategies internally.
    Implements true factory pattern: returns single object with internal strategy composition.
    """
    
    def __init__(self, strategies: List[Knowledge]):
        super().__init__()
        self.strategies = strategies
        logger.info(f"CompositeKnowledge initialized with {len(strategies)} strategies: "
                   f"{[s.__class__.__name__ for s in strategies]}")
    
    async def retrieve(self, query: str, context: Dict[str, Any] = None) -> str:
        """Iterate through strategies for knowledge retrieval, return first non-empty result."""
        for strategy in self.strategies:
            try:
                result = await strategy.retrieve(query, context)
                if result and result.strip():
                    logger.debug(f"Knowledge retrieved by {strategy.__class__.__name__}")
                    return result
            except Exception as e:
                logger.warning(f"Strategy {strategy.__class__.__name__} failed: {e}")
                continue
        return ""
    
    def add_strategy(self, strategy: Knowledge) -> None:
        """Dynamically add strategy."""
        self.strategies.append(strategy)
    
    def remove_strategy(self, strategy_class: type) -> bool:
        """Remove strategy of specified type."""
        for i, strategy in enumerate(self.strategies):
            if isinstance(strategy, strategy_class):
                del self.strategies[i]
                return True
        return False


class KnowledgeFactory:
    """Factory for creating Knowledge instances."""
    
    @staticmethod
    def create(knowledge_configs: List[Dict[str, Any]], path: Text = None) -> Optional[Knowledge]:
        """Create single Knowledge object based on configuration.
        Returns CompositeKnowledge for multiple configs, single Knowledge for one config,
        or None if no configurations provided.
        
        Args:
            knowledge_configs: List of knowledge configuration dictionaries (can be empty)
            path: Base path for knowledge resources
            
        Returns:
            Optional[Knowledge]: Single Knowledge object, CompositeKnowledge, or None if no valid config
        """
        if not knowledge_configs:
            logger.info("No knowledge configurations provided, knowledge will be disabled")
            return None
        
        # If only one config, return single Knowledge instance
        if len(knowledge_configs) == 1:
            config = knowledge_configs[0]
            try:
                return KnowledgeFactory._create_single_knowledge(config, path)
            except Exception as e:
                logger.info("Knowledge will be disabled due to configuration error")
                return None
        
        # Multiple configs: create CompositeKnowledge
        strategies = []
        for config in knowledge_configs:
            try:
                strategy = KnowledgeFactory._create_single_knowledge(config, path)
                strategies.append(strategy)
            except Exception as e:
                logger.error(f"Failed to create knowledge strategy from config {config}: {e}")
                continue
        
        if not strategies:
            logger.warning("Failed to create any knowledge strategies, knowledge will be disabled")
            return None
        
        return CompositeKnowledge(strategies)
    
    @staticmethod
    def _create_single_knowledge(config: Dict[str, Any], path: Text = None) -> Knowledge:
        """Create single Knowledge strategy instance."""
        if not config or not isinstance(config, dict):
            raise ValueError(f"Invalid knowledge config (not a dict): {config}")
            
        knowledge_type = config.get('type')
        
        if not knowledge_type:
            raise ValueError(f"Invalid knowledge config (missing type): {config}")
        
        if knowledge_type == 'llm':
            try:
                from cota.knowledge.llm_knowledge import LLMKnowledge
                llm_config = config.get('config', config)
                if not llm_config:
                    raise ValueError("LLM knowledge config is empty")
                return LLMKnowledge(config=llm_config)
            except ImportError as e:
                raise ValueError(f"LLMKnowledge not available: {e}")
            except Exception as e:
                raise ValueError(f"Failed to create LLMKnowledge: {e}")
        else:
            raise ValueError(f"Unknown knowledge type: {knowledge_type}")

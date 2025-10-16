import logging
from typing import Dict, Any, Optional, List
from cota.knowledge.knowledge import Knowledge
from cota.constant import DEFAULT_DIALOGUE_MAX_TOKENS

logger = logging.getLogger(__name__)


class LLMKnowledge(Knowledge):
    """LLM-based knowledge retrieval using language models."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Support both single llm and llms list configuration
        self.llms = config.get('llms', [])
        self.prompt_template = config.get('prompt', self._default_prompt())
        self.max_tokens = config.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS)
        self.temperature = config.get('temperature', 0.7)
        
        if not self.llms:
            raise ValueError(f"LLM configuration is required for LLMKnowledge")
        
        # Build action to LLM mapping and find default LLM
        self.action_llm_map = {}
        self.default_llm = None
        
        for llm_config in self.llms:
            llm_name = llm_config.get('name')
            action = llm_config.get('action')
            
            if not llm_name:
                logger.warning(f"LLM configuration missing name: {llm_config}")
                continue
                
            if action:
                self.action_llm_map[action] = llm_name
            else:
                # LLM without specific action serves as default
                self.default_llm = llm_name
    
    def _default_prompt(self) -> str:
        """Default prompt template for knowledge retrieval."""
        return """根据以下查询问题，提供相关的知识信息：
                查询问题: {{query}}

                对话历史:
                {{history}}

                请提供准确、有用的知识信息来帮助回答这个问题。
            """
    
    def _select_llm(self, context: Dict[str, Any] = None) -> str:
        """Select appropriate LLM based on context."""
        if context:
            # Try to get current action from context
            current_action = context.get('current_action')
            if current_action and hasattr(current_action, 'name'):
                action_name = current_action.name
            elif current_action and hasattr(current_action, '__class__'):
                action_name = current_action.__class__.__name__
            else:
                action_name = None
                
            # Check if we have a specific LLM for this action
            if action_name and action_name in self.action_llm_map:
                return self.action_llm_map[action_name]
        
        # Use default LLM if available
        if self.default_llm:
            return self.default_llm
            
        # Fallback to first available LLM
        if self.llms:
            return self.llms[0].get('name')
            
        raise ValueError("No LLM available for knowledge retrieval")
    
    async def retrieve(self, query: str, context: Dict[str, Any] = None) -> str:
        """Use LLM to generate knowledge based on query and context."""
        try:
            # Get agent from context
            agent = context.get('agent') if context else None
            if not agent:
                logger.error("Agent not provided in context for LLMKnowledge")
                return ""
            
            # Build prompt with query and context
            prompt = self._build_prompt(query, context)
            
            # Select appropriate LLM
            selected_llm = self._select_llm(context)
            
            # Call LLM
            llm_instance = agent.llm_instance(selected_llm)
            result = await llm_instance.generate_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            return result["content"]
            
        except Exception as e:
            logger.error(f"LLM knowledge retrieval failed: {e}")
            return ""
    
    def _build_prompt(self, query: str, context: Dict[str, Any] = None) -> str:
        """Build prompt from template, query and context."""
        prompt = self.prompt_template.replace('{{query}}', query)
        
        if context:
            # Add conversation history if available
            dst = context.get('dst')
            if dst:
                try:
                    history = "\n".join([
                        f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                        for msg in dst.extract_messages()[-5:]  # Last 5 messages
                    ])
                    prompt = prompt.replace('{{history}}', history)
                except Exception as e:
                    logger.warning(f"Failed to extract history: {e}")
                    prompt = prompt.replace('{{history}}', "")
            else:
                prompt = prompt.replace('{{history}}', "")
        
        return prompt

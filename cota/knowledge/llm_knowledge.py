import logging
from typing import Dict, Any
from cota.knowledge.knowledge import Knowledge
from cota.constant import DEFAULT_DIALOGUE_MAX_TOKENS

logger = logging.getLogger(__name__)


class LLMKnowledge(Knowledge):
    """LLM-based knowledge retrieval using language models."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.llm = config.get('llm')
        if not isinstance(self.llm, str) or not self.llm:
            raise ValueError('LLMKnowledge requires an llm name')
        if 'llms' in config or 'action' in config:
            raise ValueError('Action-specific knowledge routing was removed; use llm')
        self.prompt_template = config.get('prompt', self._default_prompt())
        self.max_tokens = config.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS)
        self.temperature = config.get('temperature', 0.7)

    def _default_prompt(self) -> str:
        """Default prompt template for knowledge retrieval."""
        return """根据以下查询问题，提供相关的知识信息：
                查询问题: {{query}}

                对话历史:
                {{history}}

                请提供准确、有用的知识信息来帮助回答这个问题。
            """
    
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
            selected_llm = self.llm
            
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
        
        return prompt.replace('{{history}}', '')

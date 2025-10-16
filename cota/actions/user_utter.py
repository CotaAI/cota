import logging
import json
from cota.actions.action import Action
from cota.message.message import Message
from typing import Text, Optional, Dict, List, Any
from cota.dst import DST
from cota.constant import (
    DEFAULT_DIALOGUE_MAX_TOKENS
)

logger = logging.getLogger(__name__)

class UserUtter(Action):
    """User utterance action for processing user requests"""

    def apply_to(self, dst: DST) -> None:
        """Apply user utterance to dialogue state tracker"""
        dst.actions.append(self)
        dst.formless_actions.append(self)
        dst.latest_action = self
        dst.latest_query = self
        dst.latest_sender_id = self.sender_id
        dst.latest_receiver_id = self.receiver_id

    def run_from_string(self, text: Text) -> None:
        """Create user message from text string"""
        message = Message(
            sender='user',
            text=text
        )
        self.result.append(message.as_dict())

    async def run(
            self,
            agent: Optional["Agent"] = None,
            dst: Optional[DST] = None,
            user: Optional[Dict] = None,
    ):
        """Execute user utterance action with LLM processing"""
        knowledge_dict = await dst.format_knowledge(self.prompt, self)
        thoughts_dict = await dst.format_policies(self.prompt, self)
        prompt = dst.format_prompt(self.prompt, self, {**knowledge_dict, **thoughts_dict})

        if user and user.get('description'):
            messages = [{"role": "system", "content": user.get('description')},{"role":"user", "content": prompt}]
        else:
            messages = [{"role":"user", "content": prompt}]

        result = await agent.llm_instance(self.llm).generate_chat(
            messages = messages,
            max_tokens = agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS),
            response_format={'type': 'json_object'}
        )

        # Parse JSON response from LLM
        content = result["content"]
        try:
            json_result = json.loads(content)
            text_content = json_result.get('text', '')
            thought_content = json_result.get('thought', '')
            state_content = json_result.get('state', 'continue')
            
            logger.debug(f"Parsed JSON result: {json_result}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from user: {content}")
            # Fallback to original text if JSON parsing fails
            text_content = content
            thought_content = ''
            state_content = 'continue'

        # Create message with text content
        message = Message(
            sender='user',
            text=text_content
        )
        
        # Create message dict and add thought and state at the same level as text
        message_dict = message.as_dict()
        if thought_content:
            message_dict['thought'] = thought_content
        if state_content:
            message_dict['state'] = state_content
            
        self.result.append(message_dict)
        
        logger.debug(f"Query proxy user: {user}")
        logger.debug(f"Query prompt: {prompt}")
        logger.debug(f"Query result: {self.result}")

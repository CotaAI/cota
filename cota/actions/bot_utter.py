import logging
import json
from typing import Optional, Dict, Any, List
from cota.actions.action import Action
from cota.message.message import Message
from cota.dst import DST
from cota.constant import DEFAULT_DIALOGUE_MAX_TOKENS

logger = logging.getLogger(__name__)


class BotUtter(Action):
    """
    Bot utterance action that generates responses using LLM with JSON output support.
    
    This action processes prompts through the dialogue state tracker (DST),
    formats them with RAG and thought context, and generates bot responses
    using the configured language model. The LLM is instructed to return
    responses in JSON format with 'text' and 'thought' fields.
    
    Expected JSON response format:
    {
        "text": "The main response content",
        "thought": "Internal reasoning or thought process"  
    }
    
    The 'thought' content is stored at the same level as 'text' for analysis and debugging.
    """
    def apply_to(self, dst: DST) -> None:
        """
        Apply this action to the dialogue state tracker.
        
        Args:
            dst: The dialogue state tracker to update
        """
        if dst is None:
            raise ValueError("DST cannot be None")
            
        dst.actions.append(self)
        dst.formless_actions.append(self)
        dst.latest_action = self
        dst.latest_response = self

    def run_from_string(self, text: str) -> None:
        """
        Create a bot message from a string and add it to results.
        
        Args:
            text: The text content for the bot message
        """
        if not text:
            logger.warning("Empty text provided to run_from_string")
            return
            
        if not hasattr(self, 'result'):
            self.result = []
            
        message = Message(sender='bot', text=text)
        self.result.append(message.as_dict())

    async def run(
            self,
            agent: Optional["Agent"] = None,
            dst: Optional[DST] = None,
    ):
        knowledge_dict = await dst.format_knowledge(self.prompt, self)
        thoughts_dict = await dst.format_policies(self.prompt, self)
        prompt = dst.format_prompt(self.prompt, self, {**knowledge_dict, **thoughts_dict})

        messages = [
            {
                "role": "system",
                "content": dst.agent_description()
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        # Generate response with JSON format requirement
        result = await agent.llm_instance(self.llm).generate_chat(
            messages=messages,
            max_tokens=agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS),
            response_format={'type': 'json_object'}
        )

        # Parse JSON response from content field
        content = result["content"]
        try:
            json_result = json.loads(content)
            text_content = json_result.get('text', '')
            thought_content = json_result.get('thought', '')
            
            logger.debug(f"Parsed JSON result: {json_result}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from bot: {content}")
            # Fallback to original text if JSON parsing fails
            text_content = content
            thought_content = ''

        # Create message with text content
        message = Message(sender='bot', sender_id=agent.name, text=text_content)
        
        # Create message dict and add thought at the same level as text
        message_dict = message.as_dict()
        if thought_content:
            message_dict['thought'] = thought_content

        if self.result and self.result[-1].get('text') is None:
            self.result[-1].update({
                key: value for key, value in message_dict.items() if value is not None
            })
        else:
            self.result.append(message_dict)

        logger.debug(f"Response prompt: {prompt}")
        logger.debug(f"Response result: {self.result}")

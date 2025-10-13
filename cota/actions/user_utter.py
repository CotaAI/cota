import logging
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
        dst.slots = self.extract_slots()
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
        rag_dict = await dst.format_thoughts(self.prompt, self)
        thoughts_dict = await dst.format_rag(self.prompt, self)
        prompt = dst.format_prompt(self.prompt, self, {**rag_dict, **thoughts_dict})

        if user and user.get('description'):
            messages = [{"role": "system", "content": user.get('description')},{"role":"user", "content": prompt}]
        else:
            messages = [{"role":"user", "content": prompt}]

        result = await agent.llm_instance(self.llm).generate_chat(
            messages = messages,
            max_tokens = agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS)
        )

        message = Message(
            sender='user',
            text=result
        )
        self.result.append(message.as_dict())
        logger.debug(f"Query proxy user: {user}")
        logger.debug(f"Query prompt: {prompt}")
        logger.debug(f"Query result: {self.result}")

    def extract_slots(self):
        """Extract slots from action results"""
        result = {}
        for d in [result.get('metadata',{}).get('slots',{}) for result in self.result]:
            result.update(d)
        return result
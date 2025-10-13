import logging
import re
import json
from typing import Text, Optional, List, Dict, Any
from cota.actions.action import Action
from cota.dst import DST
from cota.utils.parser import extract_action_from_string
from cota.constant import DEFAULT_SELECTOR_INSTRUCTION
from cota.constant import (
    DEFAULT_DIALOGUE_MAX_TOKENS
)

logger = logging.getLogger(__name__)

class Selector(Action):
    """Selector class for selecting the next action to execute
    """
    def __init__(
            self,
            name: Optional[Text] = None,
            description: Optional[Text] = None,
            prompt: Optional[Text] = None,
            llm: Optional[Text] = None,
            timestamp: Optional[float] = None,
            sender_id: Optional[Text] = None,
            receiver_id: Optional[Text] = None,
            result: Optional[List] = None,
            **kwargs
    ) -> None:
        """Initialize the selector
        
        Args:
            name: Name of the selector
            description: Description of the selector
            prompt: Prompt text
            llm: Language model to use
            timestamp: Timestamp
            sender_id: Sender ID
            receiver_id: Receiver ID
            result: Result list
        """
        super().__init__(
            name=name,
            description=description,
            prompt=prompt,
            llm=llm,
            timestamp=timestamp,
            sender_id=sender_id,
            receiver_id=receiver_id,
            result=result
        )

    def apply_to(self, dst: DST) -> None:
        dst.actions.append(self)
        #dst.formless_actions.append(self)
        dst.latest_action = self

    def run_from_string(self, text: Text) -> None:
        self.result.append(
            {
                "action_name": text,
            }
        )


    async def run(
            self,
            agent: Optional["Agent"] = None,
            dst: Optional[DST] = None
    ):
        # System prompt
        system_prompt = DEFAULT_SELECTOR_INSTRUCTION
        # Enhanced prompt
        rag_dict = await dst.format_thoughts(self.prompt, self)
        thoughts_dict = await dst.format_rag(self.prompt, self)
        prompt = dst.format_prompt(self.prompt, self, {**rag_dict, **thoughts_dict})

        select_result = await agent.llm_instance(self.llm).generate_chat(
            messages=[
                {"role": "system", "content": DEFAULT_SELECTOR_INSTRUCTION},
                {"role": "user", "content": prompt}
            ],
            max_tokens=agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS),
            response_format = {'type': 'json_object'}
        )
        try:
            select_result = json.loads(select_result)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from selector: {select_result}")

        logger.debug(f"Selector result before: {select_result}")
        
        result_dict = {"text": select_result.get('action')}
        if select_result.get('thought'):
            result_dict['thought'] = select_result.get('thought')
        
        self.result = [result_dict]

        logger.debug(f"Selector prompt: {prompt}")
        logger.debug(f"Selector result: {self.result}")
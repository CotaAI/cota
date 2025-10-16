import logging
from typing import Optional, Text, List, Dict
import numpy as np
from cota.actions.bot_utter import BotUtter
from cota.message.message import Message
from cota.dst import DST
from cota.constant import (
    DEFAULT_DIALOGUE_MAX_TOKENS
)

logger = logging.getLogger(__name__)

class RAG(BotUtter):
    async def run(
            self,
            agent: Optional["Agent"] = None,
            dst: Optional[DST] = None,
    ):
        """
        run RAG Action
        """
        knowledge_dict = await dst.format_knowledge(self.prompt, self)
        thoughts_dict = await dst.format_policies(self.prompt, self)
        prompt = dst.format_prompt(self.prompt, self, {**knowledge_dict, **thoughts_dict})

        # Try exact match first, then case-insensitive match for 'BotUtter'
        parent_config = agent.actions.get('BotUtter')
        if parent_config is None:
            # Try case-insensitive match
            for key, config in agent.actions.items():
                if key.lower() == 'botutter':
                    parent_config = config
                    break
        parent_config = parent_config or {}
        parent_llm = parent_config.get("llm")
        result = await agent.llm_instance(parent_llm).generate_chat(
            messages=[
                {"role": "system", "content": dst.agent_description()},
                {"role":"user", "content": prompt}
            ],
            max_tokens=agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS)
        )

        message = Message(sender='bot', text=result["content"])

        if self.result and self.result[-1].get('text') is None:
            self.result[-1].update(
                {
                    key: value for key, value in message.as_dict().items() if value is not None
                }
            )
        else:
            self.result.append(message.as_dict())

        logger.debug( f"RAG prompt: {prompt}" )
        logger.debug( f"RAG result: {self.result}" )


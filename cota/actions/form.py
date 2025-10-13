import logging
import time
import json
from typing import Text, Optional, List, Dict, Any, Tuple
from cota.actions.action import Action
from cota.dst import DST
from cota.utils.parser import extract_json_from_string
from cota.utils.common import all_keys_filled, update_existing_keys
from cota.utils.http import HttpClientManager, HttpConfig
from cota.constant import (
    DEFAULT_FORM_UPDATER_INSTRUCTION,
    DEFAULT_DIALOGUE_MAX_TOKENS
)

logger = logging.getLogger(__name__)

class Form(Action):

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
            slots: Optional[Dict] = None,
            state: Optional[Text] = None,
            executer: Optional[Dict] = None,
            updater: Optional[Dict] = None
    ) -> None:
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
        self.slots = slots or {}
        self.state = state
        self.executer = executer or {}
        self.updater = updater or {}

    @staticmethod
    def resolve_by_type(
            name: Text
    ) -> "Form":
        new_class = type(name, (Form,), {})
        new_class.__name__ = name
        return new_class

    @staticmethod
    def build_from_name(**kwargs) -> "Form":
        action_class = Form.resolve_by_type(kwargs.get("name"))
        if not action_class:
            return None
        return action_class(**kwargs)

    def apply_to(self, dst: DST) -> None:
        """
        Only add the action to the list when it is at the beginning or end
        """
        dst.current_form = self if self.state in ("start", "continue") else None

        dst.actions.append(self)
        if self.state == 'end':
            dst.formless_actions.append(self)

        # Update latest action
        dst.latest_action = self

    def run_from_dict(
            self,
            action_dict
    ) -> None:
        self.name = action_dict.get("name") or self.name
        self.timestamp = action_dict.get("timestamp") or self.timestamp
        self.sender_id = action_dict.get("sender_id") or self.sender_id
        self.receiver_id = action_dict.get("receiver_id") or self.receiver_id
        self.slots = action_dict.get("slots") or self.slots
        self.state = action_dict.get("state") or self.state
        self.result = action_dict.get("result")

    def run_from_string(self, text: Text) -> None:
        self.result.append(
            {
                "action_name": text,
            }
        )

    def as_dict(self) -> Dict[Text, Any]:
        d = {
            "name": self.__class__.__name__,
            "timestamp": self.timestamp,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "slots": self.slots,
            "state": self.state
        }
        if self.result:
            d["result"] = self.result
        return d

    async def update(self, agent, dst):
        try:
            prompt_template = self.updater.get("prompt","")
            if not prompt_template:
                return
            thoughts_dict = await dst.format_thoughts(prompt_template, self)
            rag_dict = await dst.format_rag(prompt_template, self)
            prompt = dst.format_prompt(prompt_template, self, {**rag_dict, **thoughts_dict})

            llm_name = self.updater.get("llm", None)
            update_result = await agent.llm_instance(llm_name).generate_chat(
                messages = [{"role": "system", "content": DEFAULT_FORM_UPDATER_INSTRUCTION},{"role":"user", "content": prompt}],
                max_tokens = agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS),
                response_format = {'type': 'json_object'}
            )
            try:
                update_json = json.loads(update_result)
                if len(update_json) > 0:
                    update_existing_keys(self.slots, update_json)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON response from {self.name} updater: {update_result}")
                try:
                    update_json = extract_json_from_string(update_result)
                    if len(update_json) > 0:
                        update_existing_keys(self.slots, update_json)
                except Exception as e:
                    logger.error(f"Failed to parse JSON response from {self.name} updater: {e}")
        except Exception as e:
            logger.error(f"Failed to update {self.name}: {e}")

        logger.debug( f"{self.name} updater prompt: {prompt}" )
        logger.debug( f"{self.name} updater result: {update_result}" )
        logger.debug( f"{self.name} slots after update: {self.slots}")

    async def execute(self, agent, data: Dict[Text, Any]) -> Tuple[Text, Dict]:
        """Execute form
        
        Args:
            data: Data required for execution
            
        Returns:
            Tuple[Response text, Metadata]
        """
        # First check if it's a mock execution
        if self.executer.get("mock", False):
            logger.info(f"Mock execution for {self.name}")
            output_options = self.executer.get("output", [])
            return await self._handle_mock_execution(output_options)
            
        # Get executor
        executor = agent.get_executor(self.name)
        if not executor:
            return "", {"error": f"No executor found for form: {self.name}"}
            
        return await executor.execute(data)
        
    async def _handle_mock_execution(self, data: List[Text]) -> Tuple[Text, Dict]:
        """Handle mock execution
        
        Args:
            data: Optional list of output texts
            
        Returns:
            Tuple[Response text, Metadata]
        """
        if not data:
            return "", {"error": "No mock outputs available"}
            
        # Display all available output options
        print("\nAvailable mock outputs:")
        for i, text in enumerate(data, 1):
            print(f"{i}. {text}")
            
        # Let user choose
        while True:
            try:
                choice = int(input("\nPlease select an output option (enter number): "))
                if 1 <= choice <= len(data):
                    break
                print("Invalid choice. Please enter a valid number.")
            except ValueError:
                print("Please enter a valid number.")
                
        # Get selected output
        output_text = data[choice - 1]
        
        # If output contains <text>, let user input specific text
        if "<text>" in output_text:
            user_text = input("\nPlease enter your text: ")
            output_text = output_text.replace("<text>", user_text)
                
        return output_text, {}

    async def run(
            self,
            agent: Optional["Agent"] = None,
            dst: Optional[DST] = None
    ) -> List[Action]:
        text = ""
        metadata = None

        # handle init state
        if not self.state:
            self.state = "start"
            update_existing_keys(self.slots, dst.slots)

            # try to update slots if needed
            if not all_keys_filled(self.slots):
                await self.update(agent, dst)

        # handle continue state
        elif self.state == "start" or self.state == "continue":
            # try to update slots if needed
            if not all_keys_filled(self.slots):
                await self.update(agent, dst)

            self.state = "continue"
            # check if slots are now filled
            if all_keys_filled(self.slots):
                self.state = "end"
                text, metadata = await self.execute(agent, self.slots)


        self.result.append({"text": text, "metadata": metadata})
        logger.debug( f"{self.name} result: {self.result}" )
import json
import os
import copy
import logging
from typing import Text, List, Union, Optional, Dict, Tuple
from cota.actions.action import Action
from cota.actions.form import Form
from cota.actions.user_utter import UserUtter
from cota.actions.executors.base import Executor
from cota.dst import DST
from cota.utils.io import read_yaml_from_path
from cota.processor import Processor
from cota.store import Store, MemoryStore, SQLStore
from cota.llm import LLM
from cota.dpl.dpl import DPL, DPLFactory
from cota.utils.http import HttpClientManager, HttpConfig
from cota.utils.common import (
    first_empty_key,
    merge_dicts,
    hash_str
)

from cota.constant import (
    DEFAULT_CONFIG,
    DEFAULT_FORM_CONFIG,
    DEFAULT_HTTP_CLIENT_CONFIG
)

logger = logging.getLogger(__name__)

class Agent:
    def __init__(
            self,
            name: Optional[Text] = None,
            description: Optional[Text] = None,
            actions: Optional[Dict] = None,
            llms: Optional[Dict[Text, LLM]] = None,
            dpl: Optional[List[DPL]] = None,
            store: Optional[Store] = None,
            dialogue: Optional[Dict] = None,
            user_proxy: Optional[Dict] = None
    ) -> None:
        self.name = name
        self.description = description
        self.actions = actions
        self.llms = llms
        self.dpl = dpl
        self.store = store
        self.dialogue = dialogue
        self.user_proxy = user_proxy
        self.processor = Processor(agent=self, store=self.store)
        self._executors = {}  # Dictionary to store executor instances

    @classmethod
    def load_from_path(cls, path: Text, store: Optional[Store] = None) -> "Agent":
        """
        Load agent configuration from the specified path and create an Agent instance.
        
        Args:
            path (Text): Path to the agent configuration directory
            store (Optional[Store]): Optional store instance, will create one if not provided
            
        Returns:
            Agent: Configured agent instance
        """
        logger.debug(f"Loading agent config from path: {path}")

        # Load and merge configuration files
        agent_config = read_yaml_from_path(os.path.join(path, 'agent.yml'))
        endpoints_config = read_yaml_from_path(os.path.join(path, 'endpoints.yml'))
        agent_config = cls.merge_agent_config(DEFAULT_CONFIG, agent_config)

        # Extract core configuration
        system_config = agent_config.get("system", {})
        name = system_config.get("name")
        description = system_config.get("description") 
        actions = agent_config.get("actions", {})
        dialogue = agent_config.get("dialogue", {})
        user_proxy = agent_config.get("user_proxy", {})

        # Initialize or use provided store
        if not store:
            store_config = endpoints_config.get('base_store', {})
            store = Store.create(store_config)

        # Initialize language models
        llms = {}
        for llm_name, config in endpoints_config.get('llms', {}).items():
            logger.debug(f"Initializing language model: {llm_name}")
            llms[llm_name] = LLM(config)

        # Initialize dialogue policy learning
        policy_path = os.path.join(path, "policy")
        dpl = DPLFactory.create(agent_config, policy_path)

        # Initialize executors
        executors = cls._init_executors(actions)

        # Log final configurations for debugging
        logger.debug(f"Endpoints configuration:\n{endpoints_config}")
        logger.debug(f"Agent configuration:\n{agent_config}")

        agent = cls(
            name=name,
            description=description, 
            actions=actions,
            store=store,
            llms=llms,
            dpl=dpl,
            dialogue=dialogue,
            user_proxy=user_proxy
        )
        
        agent._executors = executors
        
        return agent

    @classmethod
    def _init_executors(cls, actions: Dict) -> Dict[Text, Executor]:
        """Initialize executors
        
        Args:
            actions: Action configuration dictionary
            
        Returns:
            Dict[Text, Executor]: Executor dictionary
        """
        executors = {}
        
        for action_name, action_config in actions.items():
            if "executer" in action_config:
                executor_config = action_config["executer"]
                executor_type = executor_config.get("type", "http")  # Default to http type
                
                try:
                    executor = Executor.create(executor_type, executor_config)
                    executors[action_name] = executor
                except Exception as e:
                    logger.error(f"Failed to initialize executor for {action_name}: {str(e)}")
                    
        return executors

    def get_executor(self, action_name: Text) -> Optional[Executor]:
        """Get executor for specified action
        
        Args:
            action_name: Action name
            
        Returns:
            Optional[Executor]: Executor instance, returns None if not exists
        """
        return self._executors.get(action_name)

    async def cleanup(self):
        """Clean up resources"""
        for executor in self._executors.values():
            if hasattr(executor, 'cleanup'):
                await executor.cleanup()

    def build_action(self, action_name: Text, **kwargs) -> "Action":
        """
        Builds an action based on the provided action name and optional parameters.

        Args:
            action_name (Text): The name of the action to build.
            **kwargs: Additional parameters specific to each action type.

        Returns:
            Action: The built action instance.

        Raises:
            ValueError: If the action is not found in the configuration.
        """
        # Try exact match first, then case-insensitive match
        action_config = self.actions.get(action_name)
        if action_config is None:
            # Try case-insensitive match
            action_name_lower = action_name.lower()
            for key, config in self.actions.items():
                if key.lower() == action_name_lower:
                    action_config = config
                    action_name = key  # Use the actual key name from config
                    break
        if action_config is None:
            raise ValueError(f"Action '{action_name}' not found in actions configuration.")

        # Build parameters from config and kwargs
        params = {
            "name": action_name,
            "description": kwargs.get("description") or action_config.get("description") or action_name,
            "prompt": kwargs.get("prompt") or action_config.get("prompt"),
            "llm": kwargs.get("llm") or action_config.get("llm"),
            "sender_id": self.name
        }

        # Add form-specific parameters if needed
        if action_config.get("type") == "form" or "executer" in action_config:
            slots = {key: '' for key in action_config.get("slots", {})}
            params.update({
                "slots": kwargs.get("slots") or {key: '' for key in action_config.get("slots", {})},
                "state": kwargs.get("state"),
                "executer": action_config.get("executer"),
                "updater": action_config.get("updater")
            })
            return Form.build_from_name(**params)


        # Add any additional kwargs that might be specific to other action types
        params.update(kwargs)
        return Action.build_from_name(**params)

    async def generate_actions(self, dst: DST) -> List[Action]:
        """Generate the corresponding action based on DPL"""
        if dst.current_form:
            return await self._handle_current_form(dst)

        # First try to generate action using DPL action generator
        for dpl_instance in self.dpl:
            # Try to generate next action
            action_names = await dpl_instance.generate_actions(dst)
            if action_names:
                # Only take the first action as we only support single action
                first_action_name = action_names[0]
                return [self.build_action(first_action_name)]

        # If DPL doesn't generate action, fall back to selector
        selector = self.build_action(
            action_name='Selector'
        )
        await selector.run(agent=self, dst=dst)
        dst.update(selector)

        if len(selector.result) == 0:
            # if no action is selected, return a Response action
            return [self.build_action('BotUtter')]
        else:
            # if actions are selected, take only the first action
            action_infos = self._extract_action_info(selector)
            if action_infos:
                action_name, action_params = action_infos[0]
                return [self.build_action(action_name, **action_params)]
            else:
                return [self.build_action('BotUtter')]

    async def _handle_form_query(self, dst: DST) -> List[Action]:
        selector = self.build_action(
            action_name='Selector'
        )
        await selector.run(agent = self, dst=dst)
        dst.update(selector)
        if len(selector.result) == 0:
            return [self.build_action('BotUtter')]

        action_infos = self._extract_action_info(selector)
        if action_infos:
            # Only take the first action as we only support single action
            action_name, action_params = action_infos[0]
            if dst.current_form.name == action_name:
                return [self.build_action(
                    action_name=dst.current_form.name,
                    #slots=copy.deepcopy(dst.current_form.slots),
                    slots=action_params.get('slots', {}),
                    state="continue"
                )]
            else:
                # break current form and execute the new action
                # TODO: Output two actions here, the previous break and this new one
                return [
                    self.build_action(
                        action_name=dst.current_form.name,
                        slots=copy.deepcopy(dst.current_form.slots),
                        state="break"
                    ),
                    self.build_action(
                        action_name=action_name,
                        # slots=action_params.get('slots', {}), # TODO: Allow all actions to have slots parameter, some are empty, or fill slots when it's a form
                    )
                ]
        else:
            return [self.build_action('BotUtter')]
    
    async def _handle_current_form(self, dst: DST) -> List[Action]:
        if isinstance(dst.latest_action, UserUtter):
            return await self._handle_form_query(dst)

        required_slot = first_empty_key(dst.current_form.slots)
        if not required_slot:
            return [
                self.build_action(
                    action_name=dst.current_form.name,
                    slots=copy.deepcopy(dst.current_form.slots),
                    state="continue"
                )]

        action_config = self.actions.get(dst.current_form.name, {})
        slots_config = action_config.get("slots", {})
        return [ 
                self.build_action(
                    action_name='BotUtter',
                    description = slots_config.get(required_slot,{}).get("description",{}),
                    prompt = slots_config.get(required_slot,{}).get("prompt",{}),
                    llm = slots_config.get(required_slot,{}).get("llm",None)
                )]

    def _extract_action_info(self, selector: Action) -> List[Dict]:
        action_info = []
        
        for d in selector.result:
            action_name = d.get('text')
            metadata = d.get('metadata', {})
            
            # Extract only the fields that should be passed as action parameters
            # Based on selector implementation, result now contains 'text', 'thought' and 'slots'
            # Only 'slots' should be passed as action parameters
            action_params = {}
            if 'slots' in metadata and metadata['slots']:
                action_params['slots'] = metadata['slots']
            
            logger.debug(f"Action: {action_name}, Original metadata: {metadata}")
            logger.debug(f"Action: {action_name}, Extracted action params: {action_params}")
            
            action_info.append((action_name, action_params))
        return action_info

    def _should_response(self, dst):
        latest_action = dst.latest_action
        if isinstance(latest_action, Form) and latest_action.state == 'end':
            description = latest_action.description
            prompt = latest_action.prompt
            llm = latest_action.llm
            if latest_action.result:
                # Safely access the first result item using unpacking
                try:
                    [first_result, *_] = latest_action.result
                    metadata = first_result.get("metadata", {})
                except ValueError:
                    # Handle empty result list
                    metadata = {}
                response = Action.build_from_name(
                    name = 'BotUtter',
                    description = description,
                    prompt = prompt,
                    llm = llm,
                    result = [{'metadata': metadata}],
                    sender_id = self.name
                )
            else:
                response = Action.build_from_name(
                    name = 'BotUtter',
                    description = description,
                    prompt = prompt,
                    llm = llm,
                    sender_id = self.name
                )
            return True, response
        return False, None

    def llm_instance(self, llm_name:Optional[Text] = None) -> LLM:
        if llm_name is None:
            first_llm_name, first_llm_config = next(iter(self.llms.items()))
            return first_llm_config

        llm_config = self.llms.get(llm_name)
        if llm_config is None:
            raise ValueError(f"LLM with name '{llm_name}' not found.")
        return llm_config

    @classmethod
    def merge_agent_config(cls, default_config, config):
        """
        Merges the provided config with the default config.
        """
        import copy
        actions = config.get('actions', {})
        for action_name in actions:
            if 'executer' in actions[action_name]: 
                default_form_config = copy.deepcopy(DEFAULT_FORM_CONFIG)
                actions[action_name] = merge_dicts(default_form_config, actions[action_name])
        default_config = copy.deepcopy(DEFAULT_CONFIG)
        updated_dict = merge_dicts(default_config, config)
        return updated_dict

    def create_processor(self) -> Processor:
        """
        Creates and returns a new Processor instance.
        
        Returns:
            Processor: A new processor instance initialized with this agent and its store.
        """
        processor = Processor(
            agent=self,
            store=self.store
        )
        return processor
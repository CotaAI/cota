"""Agent — the top-level configuration and resource holder.

Loads agent.yml, initializes LLMs, ToolRegistry, Pi Skill resource paths, Policy,
Knowledge, and Store. Provides a Processor for message handling.
"""

import os
import logging
import asyncio
from typing import Text, Optional, Dict

from cota.utils.io import read_yaml_from_path
from cota.processor import Processor
from cota.store import Store
from cota.llm import LLM
from cota.policy import Policy, AllPolicy, PolicyServices, load_policy
from cota.config import validate_bot_config
from cota.knowledge.knowledge import KnowledgeFactory, Knowledge
from cota.utils.common import merge_dicts

from cota.executor.tools import ToolRegistry
from cota.executor.user_memory import create_user_memory
from cota.constant import DEFAULT_CONFIG
from cota.runtime.pi_runtime import validate_runtime_selection
from cota.executor.environment import DEFAULT_DEPLOY, ExecutionEnvironment

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        name: Optional[Text] = None,
        description: Optional[Text] = None,
        llms: Optional[Dict[Text, LLM]] = None,
        policy: Optional[Policy] = None,
        store: Optional[Store] = None,
        dialogue: Optional[Dict] = None,
        user_proxy: Optional[Dict] = None,
        knowledge: Optional[Knowledge] = None,
        environment: Optional[ExecutionEnvironment] = None,
        deploy: str = DEFAULT_DEPLOY,
        file_storage=None,
    ) -> None:
        self.name = name
        self.description = description
        self.skill_paths = []
        self.llms = llms
        self.policy = policy or AllPolicy()
        self.policy_services = PolicyServices(model=self.llm_instance)
        self.store = store
        self.dialogue = dialogue or {}
        validate_runtime_selection(self.dialogue)
        self.user_proxy = user_proxy
        self.knowledge = knowledge
        self.deploy = deploy
        self.environment = environment if environment is not None else ExecutionEnvironment.for_deployment(
            deploy, {}, base_path=os.getcwd())
        if not isinstance(self.environment, ExecutionEnvironment):
            raise TypeError('environment must be an ExecutionEnvironment')
        self.processor = Processor(agent=self, store=self.store)

        self.config_path: Optional[Text] = None
        self.workspace_path: Optional[Text] = None

        self.user_memory = None
        self._tool_registry: Optional[ToolRegistry] = None
        self._files = file_storage

    @property
    def files(self):
        from cota.files import FileStorage
        if self._files is None:
            if not self.config_path:
                raise ValueError('Set Agent.config_path before using file storage')
            self._files = FileStorage(os.path.join(self.config_path, '.cota', 'files'))
        return self._files

    @classmethod
    def load_from_path(
        cls,
        path: Text,
        store: Optional[Store] = None,
    ) -> "Agent":
        logger.debug(f"Loading agent config from path: {path}")

        agent_config = read_yaml_from_path(os.path.join(path, "agent.yml"))
        endpoints_config = read_yaml_from_path(
            os.path.join(path, "endpoints.yml")
        )
        agent_config = cls.merge_agent_config(agent_config)

        system_config = agent_config.get("system", {})
        name = system_config.get("name")
        description = system_config.get("description")
        dialogue = agent_config.get("dialogue", {})
        validate_runtime_selection(dialogue)
        user_proxy = agent_config.get("user_proxy", {})

        # Skill-based business cases
        policy = load_policy(path, agent_config.get("policy", {}))

        # Resolve file-backed SQLite paths relative to this Bot, not the CLI's
        # working directory. Store and user memory must use the same path.
        store_config = endpoints_config.get("base_store", {})
        if (store_config.get("type", "").lower() == "sql"
                and store_config.get("dialect", "mysql+pymysql").startswith("sqlite")):
            database = store_config.get("db", "cota.db")
            if database != ":memory:":
                database = os.path.abspath(os.path.join(path, database))
                os.makedirs(os.path.dirname(database), exist_ok=True)
                store_config["db"] = database

        # Store
        if not store:
            store = Store.create(store_config)

        # LLMs
        llms = {}
        for llm_name, config in endpoints_config.get("llms", {}).items():
            logger.debug(f"Initializing LLM: {llm_name}")
            llms[llm_name] = LLM(config)
            llms[llm_name].name = llm_name

        # Knowledge
        knowledge_configs = agent_config.get("knowledge", [])
        knowledge = KnowledgeFactory.create(knowledge_configs, path)

        # User memory
        user_memory = create_user_memory(endpoints_config)

        # Workspace
        workspace_path = os.path.abspath(os.path.join(path, "workspace"))
        os.makedirs(workspace_path, exist_ok=True)

        # Python extensions; Pi native tools are supplied by the execution environment.
        tool_registry = ToolRegistry()
        from cota.executor.tools.registry import ToolPolicy
        tool_config = agent_config.get('tools', {})
        tool_registry.set_policy(ToolPolicy(
            allow=tool_config.get('allow'), deny=tool_config.get('deny'),
        ))

        agent = cls(
            name=name,
            description=description,
            store=store,
            llms=llms,
            policy=policy,
            dialogue=dialogue,
            user_proxy=user_proxy,
            knowledge=knowledge,
            deploy=agent_config.get('deploy', DEFAULT_DEPLOY),
            environment=ExecutionEnvironment.for_deployment(
                agent_config.get('deploy', DEFAULT_DEPLOY), agent_config.get('environment', {}), base_path=path),
        )

        agent.config_path = path
        from cota.policy.resources import PolicyResources
        agent.policy_services = PolicyResources(endpoints_config, model=agent.llm_instance).services()
        agent.workspace_path = workspace_path
        agent._tool_registry = tool_registry
        skill_dir = os.path.abspath(os.path.join(path, 'skills'))
        agent.skill_paths = [skill_dir] if os.path.isdir(skill_dir) else []
        agent.user_memory = user_memory

        return agent

    # =========================================================================
    # Accessors
    # =========================================================================

    def get_tool_registry(self) -> ToolRegistry:
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry()
        return self._tool_registry

    def llm_instance(self, llm_name: Optional[Text] = None) -> LLM:
        if llm_name is None:
            _, first_llm = next(iter(self.llms.items()))
            return first_llm
        llm_config = self.llms.get(llm_name)
        if llm_config is None:
            raise ValueError(f"LLM with name '{llm_name}' not found.")
        return llm_config

    async def cleanup(self):
        try:
            if self._tool_registry:
                await self._tool_registry.cleanup()
        finally:
            models = {id(model): model for model in (self.llms or {}).values()}
            results = await asyncio.gather(*(model.close() for model in models.values()
                                             if callable(getattr(model, 'close', None))), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result

    def create_processor(self, message_bus=None) -> Processor:
        return Processor(agent=self, store=self.store, message_bus=message_bus)

    @classmethod
    def merge_agent_config(cls, config):
        import copy
        validate_bot_config(config)
        default_config = copy.deepcopy(DEFAULT_CONFIG)
        updated_dict = merge_dicts(default_config, config)
        return updated_dict

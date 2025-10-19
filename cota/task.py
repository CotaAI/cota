import os
import sys
import re
import json
import logging
from pathlib import Path

from typing import Optional, Text, Dict
from cota.store import Store
from cota.agent import Agent
from cota.llm import LLM
from cota.message.message import Message
from cota.utils.io import read_yaml_from_path

logger = logging.getLogger(__name__)

class Task:
    def __init__(
            self,
            description: Optional[Text] = None,
            prompt: Optional[Text] = None,
            agents: Optional[Dict] = None,
            llm: Optional[LLM] = None
    ) -> None:
        self.description = description
        self.prompt = prompt
        self.agents = agents
        self.llm = llm  # 直接存储LLM实例

    @classmethod
    def load_from_path(cls, path:Text) -> 'Task':
        logger.debug(f"Loading task config from path: {path}")

        # load task config
        task_config = read_yaml_from_path(os.path.join(path, 'task.yml'))
        endpoints_config = read_yaml_from_path(os.path.join(path, 'endpoints.yml'))

        description = task_config.get("description")
        prompt = task_config.get("prompt")
        llm_name = task_config.get("llm")

        llm = None
        if llm_name:
            llms_config = endpoints_config.get('llms', {})
            llm_config = llms_config.get(llm_name)
            if llm_config is None:
                raise ValueError(f"LLM '{llm_name}' specified in task.yml not found in endpoints.yml")
            logger.debug(f"Initializing task LLM: {llm_name}")
            llm = LLM(llm_config)
        else:
            logger.warning("No LLM specified in task.yml")
            
        store = Store.create(endpoints_config.get('base_store', {}))
        agents = cls.load_agents(path, store)
        logger.debug(f"Task Config: \n {task_config}")

        return cls(
            description = description,
            prompt = prompt,
            agents = agents,
            llm = llm
        )

    @classmethod
    def load_agents(cls, path, store: Optional[Store]=None):
        agents = {}
        agents_path = os.path.join(path,'agents')
        for item in os.listdir(agents_path):
            agent_path = os.path.join(agents_path, item)
            agent = Agent.load_from_path(agent_path, store)
            agents[agent.name] = agent
        return agents

    def get_llm(self) -> LLM:
        if self.llm is None:
            raise ValueError("No LLM configured for this task. Please specify 'llm' field in task.yml")
        return self.llm

    async def run(self):
        if self.prompt:
            logger.debug(f"Generating tasks through LLM...")
            await self.run_with_llm()
        else:
            logger.error("No prompt provided for task generation.")
            sys.exit(1)


    async def run_with_llm(self):
        # Generate plan
        next_plan = await self.generate_plans()
        while True:
            await self.execute_task(next_plan)
            next_plan = await self.generate_plans()

    async def execute_task(self, task):
        logger.debug(f"Executing task {task}")
        agent = self.agents.get(task.get('agent'))
        await agent.processor.handle_session('test_001')



    async def generate_plans(self) -> Dict:
        logger.debug(f"Generating a DAG plans through LLM...")
        prompt = self.format_prompt(self.prompt)

        llm = self.get_llm()
        result = await llm.generate_chat(
            messages = [{"role": "system", "content": "You are a task planner, good at breaking down tasks into DAG execution flows"},{"role":"user", "content": prompt}],
            max_tokens = 1000,
            response_format = {'type': 'json_object'}
        )
        print('result: ', result)
        plans = json.loads(result["content"])

        logger.debug(f"Generating plans prompt: {prompt}")

        return plans

    def format_prompt(self, prompt: Text) -> Text:
        def observe(name):
            if hasattr(self, name):
                method = getattr(self, name)
                return method()
            else:
                raise AttributeError(f"Method {name} not found")

        variable_names = re.findall(r'\{\{(\w+)\}\}', prompt)
        format_dict = {var_name: observe(var_name) for var_name in variable_names}
        for key in format_dict:
            prompt = prompt.replace('{{' + key + '}}', format_dict[key])
        return prompt

    def agent_description(self) -> Text:
        description = ""
        for _, agent in self.agents.items():
            description = description + agent.name + ":" + agent.description + '\n'
        description = description + '\n'
        return description

    def task_description(self) -> Text:
        return self.description
    
    def history_messages(self) -> Text:
        merged_messages = set()
        for name, agent in self.agents.items():
            if agent.processor.dst:
                state = agent.processor.dst.current_state()
                logger.debug(f"Task DST State {state}")
                for action in state.get('actions'):
                    for result in action.get('result'):
                        merged_messages.add(
                            (action.get('timestamp'),result.get('sender_id') + ':' + result.get('text',''))
                        )
        messages = sorted(list(merged_messages),  key=lambda x: x[0])
        result = '\n'.join([message[1] for message in messages])
        logger.debug(f"History Message {result}")
        return result
    
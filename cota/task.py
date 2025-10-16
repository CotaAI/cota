import os
import sys
import re
import json
import logging
import concurrent.futures
import asyncio
from pathlib import Path

from typing import Optional, Text, List, Dict
from cota.store import Store, MemoryStore, SQLStore
from cota.agent import Agent
from cota.llm import LLM
from cota.message.message import Message
from cota.utils.io import read_yaml_from_path
from cota.utils.parser import parser_text_with_slots

logger = logging.getLogger(__name__)

class Task:
    def __init__(
            self,
            description: Optional[Text] = None,
            prompt: Optional[Text] = None,
            agents: Optional[Dict] = None,
            plans: Optional[List[Dict]] = None,
            llm: Optional[Text] = None
    ) -> None:
        self.description = description
        self.prompt = prompt
        self.agents = agents
        self.plans = plans
        self.llm = llm

    @classmethod
    def load_from_path(cls, path:Text) -> 'Task':
        logger.debug(f"Loading task config from path: {path}")

        # load task config
        task_config = read_yaml_from_path(os.path.join(path, 'task.yml'))
        endpoints_config = read_yaml_from_path(os.path.join(path, 'endpoints.yml'))

        description = task_config.get("description")
        prompt = task_config.get("prompt")
        plans = task_config.get("plans")

        llm = LLM(endpoints_config.get('llm', {}))
        # TODO: Move this logic to init
        # plans = cls.generate_plans(task_config, llm)
        store = Store.create(endpoints_config.get('base_store', {}))
        agents = cls.load_agents(path, store)
        logger.debug(f"Task Config: \n {task_config}")

        return cls(
            description = description,
            prompt = prompt,
            agents = agents,
            plans = plans,
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

    async def run(self):
        from cota.utils.common import is_dag
        if self.plans:
            logger.debug(f"Use a DAG plans from Config")
            if is_dag(self.plans) == False:
                logging.error("Error: The generated plans are not a DAG. Exiting the program.")
                sys.exit(1)
            else:
                await self.run_with_plan()

        elif self.prompt:
            logger.debug(f"Generating a DAG plans through LLM...")
            await self.run_with_llm()
        else:
            logging.INFO("A plan can be generated through configuration or using an LLM.")
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

    async def run_with_plan(self, max_concurrent_tasks:int = 5):
        # Initialize all tasks to 'pending'
        for plan in self.plans:
            plan['status'] = 'pending'

        all_tasks = {task['name']: task for task in self.plans}
        task_status ={task['name']: task['status'] for task in self.plans}

        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        async def execute_task_with_semaphore(task):
            async with semaphore:
                await self.execute_task_with_plan(task)

        while 'pending' in task_status.values():
            ready_tasks = []
            for task_name, status in task_status.items():
                if status == 'pending':
                    dependencies = all_tasks.get(task_name).get('dependencies', [])
                    if all(task_status[dep] == 'completed' for dep in dependencies):
                        ready_tasks.append(task_name)

            if ready_tasks:
                tasks = []
                for task_name in ready_tasks:
                    tasks.append(execute_task_with_semaphore(all_tasks[task_name]))
                try:
                    await asyncio.gather(*tasks)
                except Exception as e:
                    logger.error(f"Error executing tasks: {e}")
                    raise
                for task_name in ready_tasks:
                    task_status[task_name] = 'completed'
                    logger.debug(f"Task {task_name} completed")

        print("all_tasks: ", all_tasks)

    async def execute_task_with_plan(self, task):
        logger.debug(f"Executing {task['name']}")
        agent = self.agents.get(task.get('agent'))

        query = '/start'
        slots = {}
        startquery = task.get('startquery')
        if startquery:
            slots, query = parser_text_with_slots(startquery)

        await agent.processor.handle_message(
            Message(
                receiver="bot",
                text= query,
                metadata = {
                    'slots': slots
                }
            )
        )
        logger.debug(f"Completed {task['name']}")

    async def generate_plans(self) -> List[Dict]:
        logger.debug(f"Generating a DAG plans through LLM...")
        prompt = self.format_prompt(self.prompt)

        result = await self.llm.generate_chat(
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
    
    def current_plan(self) -> Text:
        return json.dumps(self.plans)
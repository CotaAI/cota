import pytest
from cota.actions.bot_utter import BotUtter
from cota.task import Task
from cota.dst import DST

def test_generate_prompt():
    response = BotUtter()
    task = Task()
    dst = DST()
    prompt = response.run(task=task,dst=dst)
    print(prompt)
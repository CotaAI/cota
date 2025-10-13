import pytest
from cota.actions.action import Action
from cota.actions.user_utter import UserUtter
from cota.actions.bot_utter import BotUtter
from cota.actions.action import registry

def test_registry():
    print("registry: ", registry)
    for cls in registry:
        print(cls.__name__)
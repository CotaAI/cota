import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, List
from cota.llm import LLM



def test_create_client_openai():
    config = {
        'type': 'api',
        'model': 'deepseek-chat',
        'apitype': 'openai',
        'key': 'sk-4e34bb4805b8446abdfe0bd9d1a357be',
        'apibase': 'https://api.deepseek.com/v1'
    }

    llm = LLM(config)
    assert llm.type == 'api'
    assert llm.apibase == 'https://api.deepseek.com/v1'

'''
def test_generate_text():
    config = {
        'type': 'api',
        'model': 'deepseek-chat',
        'apitype': 'openai',
        'key': 'sk-4e34bb4805b8446abdfe0bd9d1a357be',
        'apibase': 'https://api.deepseek.com/v1'
    }
    llm = LLM(config)
    result = llm.generate_text('Test prompt', max_tokens=100)
    print(result)
'''


def test_generate_chat():
    config = {
        'type': 'api',
        'model': 'deepseek-chat',
        'apitype': 'openai',
        'key': 'sk-4e34bb4805b8446abdfe0bd9d1a357be',
        'apibase': 'https://api.deepseek.com/v1'
    }
    llm = LLM(config)

    messages = [{'role': 'user', 'content': 'Hello'}]
    result = llm.generate_chat(messages, max_tokens=100)

"""Compact tool outcomes and their deterministic model-facing representation."""
from copy import deepcopy
import json


def text_result(content):
    """Extract Pi text without copying image data into the result value."""
    texts = [block['text'] for block in content if block['type'] == 'text']
    return '\n'.join(texts) if texts else None


def result_content(payload):
    """Rebuild exact Pi content without duplicating an ordinary text result."""
    if 'content' in payload:
        return deepcopy(payload['content'])
    result = payload['result']
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return [{'type': 'text', 'text': text}]


def result_payload(tool, call_id, result, *, content=None, status='success', duration_ms=None, resource=None, context=None):
    payload = {'tool_call_id': call_id, 'tool': tool, 'status': status, 'result': deepcopy(result)}
    if content is not None and content != result_content(payload):
        payload['content'] = deepcopy(content)
    if duration_ms is not None:
        payload['duration_ms'] = duration_ms
    if resource is not None:
        payload['resource'] = deepcopy(resource)
    if context is not None:
        payload['context'] = deepcopy(context)
    return payload

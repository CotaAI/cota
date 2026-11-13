"""Assistant message provenance carried by bot/tool events, independent of Debug."""
from copy import deepcopy
import json
import re


def canonical_json(value):
    """JSON numbers survive JS roundtrips; booleans remain a distinct type."""
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item
    return json.dumps(normalize(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def _same(a, b):
    return canonical_json(a) == canonical_json(b)


def public_content(content):
    """Stable public decision, excluding provider reasoning and signatures."""
    return [{key: deepcopy(value) for key, value in block.items() if key in
             ({'type', 'text'} if block['type'] == 'text' else
              {'type', 'id', 'name', 'arguments', 'argumentsError'})}
            for block in content if block.get('type') in ('text', 'toolCall')]


def validate_carrier(event):
    p = event.payload
    llm = p.get('llm')
    links = [key for key in ('llm_event_id', 'tool_event_id') if key in p]
    if len(links) > 1 or (llm is not None and links):
        raise ValueError('An event has exactly one assistant source')
    for key in links:
        if not isinstance(p[key], str) or not p[key]:
            raise ValueError(f'{key} must be a nonempty event ID')
        allowed = ('tool_started', 'bot_utter') if key == 'llm_event_id' else ('bot_utter',)
        if event.type not in allowed or not event.run_id:
            raise ValueError(f'{key} requires a run-bound {"/".join(allowed)}')
    if 'llm' not in p:
        return
    if not isinstance(llm, dict) or event.type not in ('bot_utter', 'tool_started') or not event.run_id:
        raise ValueError('llm requires a run-bound bot/tool_started carrier')
    if not isinstance(llm.get('request_id'), str) or not llm['request_id']:
        raise ValueError('llm requires request_id')
    if type(llm.get('request_sequence')) is not int or llm['request_sequence'] < 1:
        raise ValueError('llm requires a positive request_sequence')
    if set(llm) - {'request_id', 'request_sequence', 'model', 'duration_ms', 'policy', 'stop_reason', 'message', 'usage', 'continuation', 'image_projection'}:
        raise ValueError('Unexpected llm fields; full provider requests/responses belong in Debug')
    if 'image_projection' in llm and (not isinstance(llm['image_projection'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', llm['image_projection'])):
        raise ValueError('llm.image_projection requires a SHA-256 fingerprint')
    if 'usage' in llm:
        usage = llm['usage']
        if (not isinstance(usage, dict) or set(usage) != {'input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'}
                or any(type(n) is not int or n < 0 for n in usage.values())):
            raise ValueError('llm.usage requires nonnegative token counters')
    if llm.get('stop_reason') not in ('stop', 'toolUse', 'length'):
        raise ValueError('llm requires a valid stop_reason')
    if 'policy' in llm and not isinstance(llm['policy'], dict):
        raise ValueError('llm.policy must be an object')
    if llm.get('model') is not None and not isinstance(llm['model'], str):
        raise ValueError('llm.model must be a string or None')
    duration = llm.get('duration_ms')
    if duration is not None and (type(duration) not in (float, int) or duration < 0):
        raise ValueError('llm.duration_ms must be nonnegative')
    if 'continuation' in llm:
        continuation = llm['continuation']
        if (not isinstance(continuation, dict) or continuation.get('role') != 'assistant'
                or not isinstance(continuation.get('content'), list)
                or continuation.get('stopReason') != llm['stop_reason']
                or any(not isinstance(continuation.get(k), str) for k in ('api', 'provider', 'model'))
                or any(not isinstance(b, dict) or b.get('type') not in ('text', 'thinking', 'toolCall')
                       for b in continuation['content'])):
            raise ValueError('Invalid Pi continuation')
        visible = public_content(continuation['content'])
        expected = llm.get('message', {}).get('content')
        if event.type == 'tool_started':
            if not _same(visible, expected):
                raise ValueError('Pi continuation differs from its public decision')
        elif (any(b['type'] == 'toolCall' for b in visible)
              or '\n'.join(b['text'] for b in visible) != p['text']):
            raise ValueError('Pi continuation differs from its public reply')
    if event.type == 'bot_utter':
        if 'message' in llm or llm['stop_reason'] == 'toolUse':
            raise ValueError('Bot text is stored once; a tool batch belongs on tool_started')
        return
    if llm['stop_reason'] not in ('toolUse', 'length'):
        raise ValueError('Tool carrier requires toolUse or length stop_reason')
    message = llm.get('message')
    if (not isinstance(message, dict) or set(message) != {'content', 'stop_reason'} or
            not isinstance(message['content'], list) or message['stop_reason'] != llm['stop_reason']):
        raise ValueError('Tool carrier requires normalized assistant message')
    ids = set()
    for block in message['content']:
        if not isinstance(block, dict):
            raise ValueError('Invalid assistant content block')
        if block.get('type') == 'text':
            if set(block) != {'type', 'text'} or not isinstance(block['text'], str):
                raise ValueError('Invalid assistant text')
        elif block.get('type') == 'toolCall':
            if (set(block) - {'type', 'id', 'name', 'arguments', 'argumentsError'} or
                    any(not isinstance(block.get(k), str) or not block[k] for k in ('id', 'name')) or
                    not isinstance(block.get('arguments'), dict) or block['id'] in ids or
                    ('argumentsError' in block and not isinstance(block['argumentsError'], str))):
                raise ValueError('Invalid or duplicate assistant tool call')
            ids.add(block['id'])
        else:
            raise ValueError('Unsupported assistant content block')
    if not ids or not _matches_call(event, event):
        raise ValueError('Tool carrier must match a call in its assistant message')


def _matches_call(event, owner):
    return any(b.get('type') == 'toolCall' and b['id'] == event.payload.get('tool_call_id')
               and b['name'] == event.payload.get('tool')
               and _same(b['arguments'], event.payload.get('requested_arguments', event.payload.get('arguments')))
               for b in owner.payload['llm']['message']['content'])


def validate_carrier_references(event, events, *, event_map=None):
    p = event.payload
    llm = p.get('llm')
    if llm:
        for previous in events:
            old = previous.payload.get('llm')
            if old and (old['request_id'] == llm['request_id'] or
                        (previous.run_id == event.run_id and old['request_sequence'] == llm['request_sequence'])):
                raise ValueError('Model request already has an assistant carrier')
    if event.type == 'tool_started':
        proposal = next((previous for previous in events if previous.run_id == event.run_id
                         and previous.type == 'tool_started' and previous.payload.get('llm', {}).get('message')
                         and any(block.get('id') == p['tool_call_id'] for block in previous.payload['llm']['message']['content']
                                 if block['type'] == 'toolCall')), None)
        if proposal is not None and p.get('llm_event_id') != proposal.event_id:
            if not any(e.type == 'tool_started' and e.run_id == event.run_id
                       and e.payload['tool_call_id'] == p['tool_call_id'] for e in events):
                raise ValueError('A proposed tool call must reference its original assistant carrier')
    for key in ('llm_event_id', 'tool_event_id'):
        if key not in p:
            continue
        if event_map is not None:
            owner = event_map.get(p[key])
        else:
            owner = next((e for e in events if e.event_id == p[key]), None)
        if owner is None or owner.type != 'tool_started' or owner.run_id != event.run_id:
            raise ValueError(f'{key} must reference an earlier tool_started in its own run')
        if key == 'llm_event_id':
            message = owner.payload.get('llm', {}).get('message')
            if event.type == 'tool_started':
                if not message or not _matches_call(event, owner):
                    raise ValueError('Tool call does not match its assistant carrier')
            else:
                text = '\n'.join(b['text'] for b in (message or {}).get('content', []) if b['type'] == 'text')
                if not text or event.text != text or p.get('attachments'):
                    raise ValueError('Bot commentary must match its assistant carrier text')
                if any(e.type == 'bot_utter' and e.payload.get('llm_event_id') == owner.event_id for e in events):
                    raise ValueError('Duplicate bot commentary for assistant carrier')
        if key == 'tool_event_id' and (p.get('metadata') or {}).get('tool_call_id', owner.payload['tool_call_id']) != owner.payload['tool_call_id']:
            raise ValueError('Bot tool_call_id disagrees with its source tool event')


def assistant_from_event(event):
    """Project one owner only. Followers and tool-generated utterances add nothing."""
    from cota.events.context import assistant_message
    p = event.payload
    projection = p.get('llm', {}).get('image_projection')

    def measured(message):
        if projection:
            message['cotaImageProjection'] = projection
        return message
    usage = p.get('llm', {}).get('usage', {})
    usage = {'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0}, **usage} if usage else None
    if event.type == 'bot_utter' and not p.get('tool_event_id') and not p.get('llm_event_id'):
        llm = p.get('llm', {})
        if llm.get('continuation'):
            return measured(deepcopy(llm['continuation']))
        return measured(assistant_message({'content': p['text'], 'finish_reason': llm.get('stop_reason'), 'usage': usage}, int(event.timestamp * 1000)))
    if event.type == 'tool_started' and p.get('llm'):
        if p['llm'].get('continuation'):
            return measured(deepcopy(p['llm']['continuation']))
        original = p['llm']['message']
        message = assistant_message({'usage': usage}, int(event.timestamp * 1000))
        message.update(content=deepcopy(original['content']), stopReason=original['stop_reason'])
        return measured(message)
    return None

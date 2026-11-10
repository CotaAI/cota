"""Deterministic model-context projection. No model, tool or filesystem I/O."""
import json


def assistant_message(response, timestamp):
    """Normalize exactly the message consumed by the Pi bridge."""
    content = []
    if response.get('content'):
        content.append({'type': 'text', 'text': response['content']})
    for call in response.get('tool_calls') or []:
        fn = call['function']
        block = {'type': 'toolCall', 'id': call['id'], 'name': fn['name'], 'arguments': {}}
        try:
            arguments = json.loads(fn.get('arguments') or '{}')
            if not isinstance(arguments, dict):
                raise ValueError('Expected an object')
            block['arguments'] = arguments
        except (ValueError, TypeError) as error:
            block['argumentsError'] = f"Invalid JSON arguments: {fn.get('arguments')}; {error}"
        content.append(block)
    return {'role': 'assistant', 'content': content, 'timestamp': timestamp,
            'api': 'openai-completions', 'provider': 'cota', 'model': 'cota-configured-model',
            'usage': response.get('usage') or {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0,
                'totalTokens': 0, 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0}},
            'stopReason': 'length' if response.get('finish_reason') == 'length' else
                'toolUse' if any(c['type'] == 'toolCall' for c in content) else 'stop'}


def validate_context(messages):
    if not isinstance(messages, list):
        raise ValueError('context_messages must be a list')
    ids = set()
    for message in messages:
        if (not isinstance(message, dict) or message.get('role') not in ('user', 'assistant', 'toolResult')
                or not isinstance(message.get('cotaEventId'), str) or not message['cotaEventId']
                or message['cotaEventId'] in ids or 'content' not in message):
            raise ValueError('Invalid context message or duplicate identity')
        ids.add(message['cotaEventId'])


def user_content(event):
    """Single-chat text stays plain; group identity remains structured user data."""
    metadata = event.payload.get('metadata') or {}
    if metadata.get('mode') != 'group':
        if event.payload.get('attachments'):
            return json.dumps({'text': event.text, 'attachments': event.payload['attachments']}, ensure_ascii=False)
        return event.text
    identity = {'id': metadata['sender_id']}
    if metadata.get('sender_name'):
        identity['name'] = metadata['sender_name']
    value = {'speaker': identity, 'text': event.text}
    if event.payload.get('attachments'):
        value['attachments'] = event.payload['attachments']
    if metadata.get('mentioned'):
        value['mentions_bot'] = True
    if metadata.get('reply_to'):
        value['reply_to'] = metadata['reply_to']
    return json.dumps(value, ensure_ascii=False)


def apply_context(messages, event, *, active_run, trigger_event=None, deferred_input_ids=()):
    """Return a new projection only when this fact affects model context."""
    p, kind = event.payload, event.type
    message = None
    if kind == 'run_started' and (p.get('mode') == 'group' or p.get('context_input_id')):
        # Use immutable input chronology, not projected message positions:
        # an older explicitly retried trigger may have moved to context end.
        deferred_ids = set(deferred_input_ids)
        immediate = [m for m in messages if m['cotaEventId'] not in deferred_ids]
        deferred = [{**m, 'cotaDeferred': True} for m in messages if m['cotaEventId'] in deferred_ids]
        # A recorded mention explicitly retried later still targets its original
        # user text, even if that text was already summarized in a newer run.
        trigger = next((m for m in immediate if m['cotaEventId'] == p['input_event_id']), None)
        if trigger is None:
            if trigger_event is None:
                raise ValueError('Group trigger must reference a user message')
            trigger = {'role': 'user', 'content': user_content(trigger_event),
                       'timestamp': int(trigger_event.timestamp * 1000),
                       'cotaEventId': trigger_event.event_id}
            if trigger_event.payload.get('attachments'):
                trigger['cotaAttachments'] = trigger_event.payload['attachments']
        immediate = [m for m in immediate if m['cotaEventId'] != p['input_event_id']]
        return immediate + [trigger] + deferred
    if kind == 'user_utter':
        message = {'role': 'user', 'content': user_content(event)}
        if p.get('attachments'):
            message['cotaAttachments'] = p['attachments']
        if active_run:
            message['cotaDeferred'] = True
    elif kind == 'bot_utter':
        from cota.events.assistant import assistant_from_event
        message = assistant_from_event(event)
        if message is None:
            return messages
    elif event.run_id != active_run or active_run is None:
        return messages
    elif kind == 'tool_started' and p.get('llm'):
        from cota.events.assistant import assistant_from_event
        message = assistant_from_event(event)
    elif kind == 'tool_result':
        from cota.events.tool import result_content
        message = {'role': 'toolResult', 'toolCallId': p['tool_call_id'], 'toolName': p['tool'],
                   'content': result_content(p), 'isError': p['status'] != 'success'}
        message['cotaResultEventId'] = event.event_id
    elif kind == 'run_finished':
        return [{k: v for k, v in m.items() if k != 'cotaDeferred'}
                for m in finish_context(messages, event)]
    elif kind == 'context_compaction':
        ids = p['replaced_message_ids']
        if not ids or [m['cotaEventId'] for m in messages[:len(ids)]] != ids:
            raise ValueError('Compaction must replace an exact current context prefix')
        message = {'role': 'user', 'content': '<historical_summary>\n' + p['summary'] + '\n</historical_summary>',
                   'timestamp': int(event.timestamp * 1000), 'cotaEventId': event.event_id,
                   'cotaCompaction': True}
        return [message] + messages[len(ids):]
    if message is None:
        return messages
    message.update(timestamp=int(event.timestamp * 1000), cotaEventId=event.event_id)
    if event.run_id and kind != 'user_utter':
        message['cotaRunId'] = event.run_id
    if kind != 'user_utter' and active_run:
        immediate = [m for m in messages if not m.get('cotaDeferred')]
        deferred = [m for m in messages if m.get('cotaDeferred')]
        return immediate + [message] + deferred
    return messages + [message]


def finish_context(messages, event):
    """Close missing protocol replies, without claiming an actual tool outcome.

    Keep real results and insert notices before the next non-tool message. IDs
    derive from the terminal event and call position, so replay/snapshots agree.
    Notices never have cotaResultEventId and cannot prove Skill reads or effects.
    """
    result, index = [], 0
    while index < len(messages):
        message = messages[index]
        result.append(message)
        index += 1
        if message.get('cotaRunId') != event.run_id or message['role'] != 'assistant':
            continue
        calls = [b for b in message['content'] if b.get('type') == 'toolCall']
        if not calls:
            continue
        received = set()
        while (index < len(messages) and messages[index]['role'] == 'toolResult'
               and messages[index].get('cotaRunId') == event.run_id):
            received.add(messages[index]['toolCallId'])
            result.append(messages[index])
            index += 1
        for position, call in enumerate(calls):
            if call['id'] in received:
                continue
            result.append({
                'role': 'toolResult', 'toolCallId': call['id'], 'toolName': call['name'],
                'content': [{'type': 'text', 'text':
                    '[Cota execution notice, not a tool response] This run ended without a recorded '
                    'result for this call. Its external outcome is unknown, not confirmed failure. '
                    'Verify the external state before repeating any operation with side effects.'}],
                'isError': True, 'timestamp': int(event.timestamp * 1000),
                'cotaEventId': f"{event.event_id}:missing:{message['cotaEventId']}:{position}",
                'cotaRunId': event.run_id, 'cotaRecovery': True,
            })
    return result

"""Public message projection shared by application and channel adapters."""

def message_record(session_id, event):
    """Public conversation projection; tool data, prompts and DST stay private."""
    payload = event['payload']
    metadata = payload.get('metadata') or {}
    text = payload['text']
    if metadata.get('source') == 'runtime_error':
        text = '抱歉，处理时遇到错误，请稍后重试。'
    return {'type': 'message', 'session_id': session_id, 'event_id': event['event_id'],
            'sequence': event['sequence'], 'timestamp': event['timestamp'], 'role': 'user' if event['type'] == 'user_utter' else 'bot',
            'text': text, 'message_id': metadata.get('message_id'),
            **({key: metadata[key] for key in ('sender_id', 'sender_name', 'mentioned', 'reply_to')
                if key in metadata} if metadata.get('mode') == 'group' else {})}

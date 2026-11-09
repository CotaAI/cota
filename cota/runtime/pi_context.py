"""Message format boundary; no agent scheduling or tool execution here."""
import json


def text_content(content):
    if isinstance(content, str):
        return content
    return '\n'.join(c.get('text', '') for c in (content or []) if c.get('type') == 'text')


def to_openai(messages, system_prompt):
    result = [{'role': 'system', 'content': system_prompt}]
    pending_images = []

    def flush_images():
        if pending_images:
            result.append({'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f"data:{c['mimeType']};base64,{c['data']}"}}
                for c in pending_images]})
            pending_images.clear()

    for message in messages:
        role = message['role']
        content = message.get('content', '')
        if role == 'system':
            continue
        if role != 'toolResult':
            flush_images()
        if role == 'user':
            if isinstance(content, list):
                content = [({'type': 'image_url', 'image_url': {
                    'url': f"data:{c['mimeType']};base64,{c['data']}"}}
                    if c['type'] == 'image' else c) for c in content]
            result.append({'role': 'user', 'content': content})
        elif role == 'assistant':
            entry = {'role': 'assistant', 'content': text_content(content)}
            calls = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}}
                for c in content if c['type'] == 'toolCall']
            if calls:
                entry['tool_calls'] = calls
            result.append(entry)
        elif role == 'toolResult':
            result.append({'role': 'tool', 'tool_call_id': message['toolCallId'],
                           'content': text_content(content)})
            pending_images.extend(c for c in content if c['type'] == 'image')
    flush_images()
    return result

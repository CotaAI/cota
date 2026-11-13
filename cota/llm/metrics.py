"""Bounded request diagnostics; character counts never pretend to be token usage."""
import json
import re


def request_metrics(request):
    sections = {'system': 0, 'user': 0, 'assistant': 0, 'tool_results': 0}
    images, image_bytes = 0, 0
    runtime_context_chars, business_guidance_chars = 0, 0
    system_sections = {'business_guidance': 0, 'skill_catalog': 0, 'base_and_environment': 0}
    for message in request.get('messages', []):
        content = message.get('content') or ''
        text = content if isinstance(content, str) else '\n'.join(
            block.get('text', '') for block in content if block.get('type') == 'text')
        if message.get('tool_calls'):
            text += json.dumps(message['tool_calls'], ensure_ascii=False)
        role = 'tool_results' if message.get('role') == 'tool' else message.get('role')
        if role in sections:
            sections[role] += len(text)
        runtime_context_chars += sum(len(m.group()) for m in re.finditer(r'<runtime_context>.*?</runtime_context>', text, re.S))
        business_guidance_chars += sum(len(m.group()) for m in re.finditer(r'<business_guidance>.*?</business_guidance>', text, re.S))
        if role == 'system':
            sizes = {}
            for name, tag in (('business_guidance', 'business_guidance'), ('skill_catalog', 'available_skills')):
                sizes[name] = sum(len(m.group()) for m in re.finditer(f'<{tag}>.*?</{tag}>', text, re.S))
                system_sections[name] += sizes[name]
            system_sections['base_and_environment'] += len(text) - sum(sizes.values())
        if isinstance(content, list):
            for block in content:
                if block.get('type') != 'image_url':
                    continue
                images += 1
                url = block.get('image_url', {}).get('url', '')
                if url.startswith('data:') and ';base64,' in url:
                    encoded = url.split(';base64,', 1)[1]
                    image_bytes += max(0, len(encoded) * 3 // 4 - len(encoded) + len(encoded.rstrip('=')))
    return {'text_chars': sum(sections.values()), 'sections': sections,
            'system_sections': system_sections,
            'runtime_context_chars': runtime_context_chars, 'business_guidance_chars': business_guidance_chars,
            'tool_definition_chars': len(json.dumps(request.get('tools', []), ensure_ascii=False)),
            'images': images, 'inline_image_bytes': image_bytes}


def usage_metrics(response):
    usage = response.get('usage')
    if not isinstance(usage, dict):
        return None
    result = {key: usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
              if type(usage.get(key)) is int and usage[key] >= 0}
    for field, key in (('prompt_tokens_details', 'cached_tokens'), ('completion_tokens_details', 'reasoning_tokens')):
        value = (usage.get(field) or {}).get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    return result or None

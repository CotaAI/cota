"""Bounded observations for Policy retrieval; never inferred business completion."""
from dataclasses import dataclass
from copy import deepcopy
import json
from cota.events.tool import result_content


def _text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(block.get('text', '') for block in (content or []) if block.get('type') == 'text')


@dataclass(frozen=True)
class PolicyContext:
    session_id: str
    observations: tuple = ()
    available_skills: tuple = ()
    read_skills: tuple = ()

    def as_dict(self):
        return deepcopy({'session_id': self.session_id, 'observations': list(self.observations),
                         'available_skills': list(self.available_skills), 'read_skills': list(self.read_skills)})

    @property
    def evidence_ids(self):
        return {item['event_id'] for item in self.observations if item.get('event_id')}

    def text(self, field='conversation'):
        if field == 'latest_user':
            return next((o['text'] for o in reversed(self.observations) if o['role'] == 'user'), '')
        roles = {'tool'} if field == 'tool_results' else {'user', 'assistant', 'tool'}
        return '\n'.join(o.get('retrieval_text', o['text']) for o in self.observations if o['role'] in roles)

    @classmethod
    def from_runtime(cls, messages, dst, available_skills, read_skills, max_chars=16000):
        events = list(dst.events)
        facts = {e.event_id: e for e in events}
        starts = {(e.run_id, e.payload['tool_call_id']): e for e in events if e.type == 'tool_started'}
        used, observations, remaining = set(), [], max_chars - 2
        latest_user = next((i for i in range(len(messages) - 1, -1, -1)
                            if messages[i].get('role') == 'user'), None)
        reserve = min(max_chars // 3, len(_text(messages[latest_user].get('content')))) + 250 if latest_user is not None else 0
        # Match the newest visible messages first; a repeated text must not attach
        # several different historical events. Summaries have no factual event ID.
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            role = message.get('role')
            if role not in ('user', 'assistant', 'toolResult'):
                continue
            text = _text(message.get('content'))
            item = {'role': 'tool' if role == 'toolResult' else role, 'text': text}
            if role == 'assistant':
                item['retrieval_text'] = text
                calls = [b for b in message.get('content', []) if isinstance(b, dict) and b.get('type') == 'toolCall']
                if calls:
                    item['text'] += '\n' + json.dumps([
                        {'tool': b['name'], 'arguments': b.get('arguments', {})} for b in calls], ensure_ascii=False)
            if not item['text']:
                continue
            if role == 'toolResult':
                item['tool'] = message.get('toolName')
                if message.get('cotaRecovery'):
                    item.update(source='runtime', outcome='unknown')
                if message.get('toolName') == 'read':
                    # Skill instructions and paths are available to the judge,
                    # but must not turn every case for that Skill into a lexical hit.
                    item['retrieval_text'] = ''
                event = facts.get(message.get('cotaResultEventId'))
                if (event and event.type == 'tool_result'
                        and event.payload['tool_call_id'] == message.get('toolCallId')
                        and event.tool == message.get('toolName')
                        and result_content(event.payload) == message.get('content')):
                    item.update(event_id=event.event_id, tool=event.tool,
                                status=event.payload['status'])
                    start = starts.get((event.run_id, event.payload['tool_call_id']))
                    item['text'] = json.dumps({'arguments': start.payload['arguments'] if start else {}, 'result': text}, ensure_ascii=False)
            elif role in ('user', 'assistant'):
                event = facts.get(message.get('cotaEventId'))
                from cota.events.assistant import assistant_from_event, _same
                from cota.events.context import user_content
                original = assistant_from_event(event) if event and role == 'assistant' else None
                matches = (event is not None and role == 'user' and event.type == 'user_utter' and user_content(event) == text)
                if original is not None:
                    matches = _same(original['content'], message.get('content'))
                if matches:
                    item['event_id'] = event.event_id
                elif not message.get('cotaEventId') and (
                        role == 'user' or isinstance(message.get('content'), str) or
                        all(isinstance(block, dict) and block.get('type') == 'text'
                            for block in (message.get('content') or []))):
                    # External plain dialogue may match text; proposed tool calls
                    # require an exact persisted assistant carrier identity.
                    event_type = 'user_utter' if role == 'user' else 'bot_utter'
                    event = next((e for e in reversed(events) if e.type == event_type
                                  and e.event_id not in used and e.text == text), None)
                    if event:
                        item['event_id'] = event.event_id
                        used.add(event.event_id)
            # Cap each observation too, so one large tool output cannot evict all
            # dialogue context. Truncated excerpts are explicitly identified.
            if index == latest_user:
                reserve = 0
            budget = remaining - reserve
            copies = 2 if item.get('retrieval_text') else 1
            allowance = min((budget - 250) // copies, max_chars // 3)
            if allowance <= 0:
                continue
            if len(item['text']) > allowance:
                item['text'] = item['text'][:allowance]
                item['truncated'] = True
            if 'retrieval_text' in item:
                item['retrieval_text'] = item['retrieval_text'][:allowance]
            size = len(json.dumps(item, ensure_ascii=False))
            while size + 2 > budget and item['text']:
                cut = max(1, (size + 2 - budget) // copies)
                item['text'] = item['text'][:-cut]
                if item.get('retrieval_text'):
                    item['retrieval_text'] = item['retrieval_text'][:-cut]
                item['truncated'] = True
                size = len(json.dumps(item, ensure_ascii=False))
            if size + 2 > budget:
                continue
            remaining -= size + 2
            observations.append(item)
        return cls(dst.session_id, tuple(reversed(observations)), tuple(available_skills), tuple(read_skills))

"""Tool result event."""
from uuid import uuid4

from cota.events.event import EventType
from cota.events.event import Event


class ToolResultEvent(Event):
    """Observed outcome; arguments and model origin belong to tool_started."""
    def __init__(self, tool: str, result=None, *, tool_call_id=None, content=None,
                 status='success', duration_ms=None, resource=None, context=None, **kw):
        from cota.events.utils.tool import result_payload
        super().__init__(EventType.TOOL_RESULT, result_payload(
            tool, tool_call_id or uuid4().hex, result, content=content, status=status,
            duration_ms=duration_ms, resource=resource, context=context), **kw)

    def _validate_payload(self):
        p = self.payload
        if 'result' not in p:
            raise ValueError('tool_result requires result')
        if p.get('status') not in ('success', 'error', 'blocked'):
            raise ValueError('Invalid tool_result status')
        if set(p) - {'tool_call_id', 'tool', 'status', 'result', 'content', 'duration_ms', 'resource', 'context'}:
            raise ValueError('Unexpected tool_result fields; arguments belong on tool_started')
        if 'content' in p:
            blocks = p['content']
            if not isinstance(blocks, list) or any(not isinstance(b, dict) or not isinstance(b.get('type'), str) for b in blocks):
                raise ValueError('content must contain Pi content blocks')
        if 'context' in p:
            ctx = p['context']
            if (not isinstance(ctx, dict) or ctx.get('mode') not in ('summary',)
                    or not isinstance(ctx.get('summary'), str) or not ctx['summary']):
                raise ValueError('context requires mode and a nonempty summary')
        return {'tool_call_id': str, 'tool': str, 'status': str}

"""Recorded read results for tests; authored Policy examples never use these."""
from cota.events import ToolResultEvent


def skill_result(skill, text=None, *, path=None, tool_call_id=None, **kw):
    path = path or f'/skills/{skill}/SKILL.md'
    return ToolResultEvent('read', result=text if text is not None else f'Instructions for {skill}', tool_call_id=tool_call_id, resource={'kind': 'skill', 'skill': skill, 'path': path}, **kw)

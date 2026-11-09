"""Compact read provenance, separate from tool output and business ownership."""
import re


def skill_read_name(event):
    """A successful Skill document read, never proof of business completion."""
    p = event.payload
    resource = p.get('resource') or {}
    if (event.type == 'tool_result' and p.get('tool') == 'read'
            and p.get('status') == 'success'
            and resource.get('kind') == 'skill'):
        return resource['skill']
    return None


def validate_resource(event):
    if 'resource' not in event.payload:
        return
    resource = event.payload['resource']
    if event.type != 'tool_result' or event.payload.get('tool') != 'read':
        raise ValueError('resource is only valid on read tool results')
    if (not isinstance(resource, dict) or
            not {'kind', 'skill', 'path'} <= resource.keys() or
            resource.keys() - {'kind', 'skill', 'path', 'hash', 'range'}):
        raise ValueError('resource requires kind, skill, path and optional hash/range')
    if resource['kind'] not in ('skill', 'reference'):
        raise ValueError('Invalid resource kind')
    if any(not isinstance(resource[k], str) or not resource[k].strip() for k in ('skill', 'path')):
        raise ValueError('resource skill/path must be nonempty strings')
    if 'hash' in resource and (not isinstance(resource['hash'], str) or
                             not re.fullmatch(r'sha256:[0-9a-f]{64}', resource['hash'])):
        raise ValueError('Invalid resource hash')
    if 'range' in resource:
        partial = resource['range']
        if not isinstance(partial, dict) or not partial or partial.keys() - {'offset', 'limit', 'truncated'}:
            raise ValueError('Invalid resource range')
        for key in ('offset', 'limit'):
            if key in partial and (type(partial[key]) not in (int, float)):
                raise ValueError('resource range offset/limit must be numbers')
        if 'truncated' in partial and partial['truncated'] is not True:
            raise ValueError('resource range truncated must be true when present')

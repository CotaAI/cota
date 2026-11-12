"""Resource provenance saved alongside events, never inside DST snapshots."""
from copy import deepcopy

from cota.events import Event
from cota.events.event import _json_native


def validate_run_metadata(metadata, events):
    if not isinstance(metadata, dict) or not _json_native(metadata):
        raise ValueError('Run metadata must be a JSON object')
    runs = {e.run_id if isinstance(e, Event) else e.get('run_id') for e in events
            if (e.type if isinstance(e, Event) else e.get('type')) == 'run_started'}
    for run_id, data in metadata.items():
        if not isinstance(run_id, str) or not run_id or run_id not in runs:
            raise ValueError('Run metadata requires an existing run_started')
        if (not isinstance(data, dict) or 'available_skills' not in data or
                set(data) - {'available_skills', 'discovery', 'deploy', 'environment', 'native_tools'}):
            raise ValueError('Invalid run metadata fields')
        names = data['available_skills']
        if (not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names)
                or len(set(names)) != len(names)):
            raise ValueError('available_skills must contain unique nonempty names')
        if 'discovery' in data and not isinstance(data['discovery'], dict):
            raise ValueError('discovery must be a JSON object')
        if 'deploy' in data:
            from cota.executor.environment import validate_deploy
            validate_deploy(data['deploy'])
            if 'environment' not in data:
                raise ValueError('Run deploy requires environment provenance')
        if 'environment' in data:
            from cota.executor.environment import ExecutionEnvironment
            value = data['environment']
            if not isinstance(value, dict) or set(value) - {'type', 'workspace', 'timeout_seconds', 'shell'}:
                raise ValueError('Invalid run environment')
            # Historical provenance must not resolve today's paths/symlinks.
            environment = ExecutionEnvironment(**value)
            if environment.to_dict() != data['environment']:
                raise ValueError('Run environment must contain the canonical execution binding')
        if 'native_tools' in data:
            if 'environment' not in data:
                raise ValueError('Native tool inventory requires environment provenance')
            environment.validate_inventory(data['native_tools'], has_skills=bool(names))
    return deepcopy(metadata)

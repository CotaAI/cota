"""Trusted deployment binding for Pi's native tools, never model-supplied arguments.

Machine execution is deliberately unrestricted: workspace is a cwd, not an isolation boundary.
Remote devices and sandboxes require real backends before they can be configured.
"""
from dataclasses import dataclass
from math import isfinite
from pathlib import Path


NATIVE_TOOLS = frozenset({'read', 'write', 'edit', 'bash', 'grep', 'find', 'ls', 'powershell'})
DEFAULT_DEPLOY = 'personal'


def validate_deploy(deploy):
    if deploy not in ('personal', 'service'):
        raise ValueError('deploy must be personal or service')


@dataclass(frozen=True)
class ExecutionEnvironment:
    type: str = 'none'
    workspace: str | None = None
    timeout_seconds: float = 60
    shell: str = 'auto'

    @classmethod
    def for_deployment(cls, deploy, config, *, base_path):
        """Resolve trusted deployment defaults once, relative to the Bot directory."""
        validate_deploy(deploy)
        if not isinstance(config, dict):
            raise ValueError('environment must be an object')
        config = {'type': 'machine', **config}
        if config['type'] == 'machine':
            config = {'workspace': 'files', **config}
        environment = cls.from_config(config, base_path=base_path)
        return environment

    def __post_init__(self):
        if self.type not in ('none', 'machine'):
            raise ValueError('environment.type must be none or machine; other backends are not implemented')
        if self.shell not in ('auto', 'bash', 'powershell', 'both'):
            raise ValueError('environment.shell must be auto, bash, powershell or both')
        if self.type == 'none' and self.shell != 'auto':
            raise ValueError('environment.shell requires type: machine')
        if (type(self.timeout_seconds) not in (int, float)
                or not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError('environment.timeout_seconds must be positive and finite')
        if self.type == 'machine':
            if not isinstance(self.workspace, str) or not self.workspace.strip() or not Path(self.workspace).is_absolute():
                raise ValueError('Machine environment requires an absolute workspace binding')
        elif self.workspace is not None:
            raise ValueError('environment.workspace requires type: machine')

    @classmethod
    def from_config(cls, config, *, base_path):
        if not isinstance(config, dict) or set(config) - {'type', 'workspace', 'timeout_seconds', 'shell'}:
            raise ValueError('environment accepts type, workspace, timeout_seconds and shell')
        kind = config.get('type', 'none')
        if kind == 'none' and set(config) - {'type'}:
            raise ValueError('environment type none does not accept machine options')
        workspace = config.get('workspace')
        if kind == 'machine':
            if not isinstance(workspace, str) or not workspace.strip():
                raise ValueError('environment.workspace is required for machine execution')
            workspace = str((Path(base_path) / Path(workspace).expanduser()).resolve())
        return cls(kind, workspace, config.get('timeout_seconds', 60), config.get('shell', 'auto'))

    def tool_names(self, *, has_skills=False):
        if self.type == 'none':
            return frozenset({'read'} if has_skills else ())
        omitted = {'powershell'} if self.shell == 'bash' else {'bash'} if self.shell == 'powershell' else set()
        return NATIVE_TOOLS - omitted

    def validate_inventory(self, inventory, *, has_skills=False):
        """Validate worker-reported availability without probing historical hosts."""
        if not isinstance(inventory, dict) or set(inventory) != {'available', 'unavailable'}:
            raise ValueError('Invalid native tool inventory')
        available, unavailable = inventory['available'], inventory['unavailable']
        if (not isinstance(available, list) or any(not isinstance(n, str) for n in available)
                or len(set(available)) != len(available) or not isinstance(unavailable, dict)
                or any(not isinstance(reason, str) or not reason.strip() for reason in unavailable.values())):
            raise ValueError('Invalid native tool availability')
        names = set(available)
        if names & unavailable.keys() or names | unavailable.keys() != self.tool_names(has_skills=has_skills):
            raise ValueError('Native tool inventory does not match environment')
        required = {'read', 'write', 'edit', 'ls'} if self.type == 'machine' else self.tool_names(has_skills=has_skills)
        if self.type == 'machine' and self.shell != 'auto':
            required |= {'bash', 'powershell'} if self.shell == 'both' else {self.shell}
        if not required <= names:
            raise ValueError('Required native tools are unavailable')
        return names

    def to_dict(self):
        if self.type == 'none':
            return {'type': 'none'}
        return {'type': 'machine', 'workspace': self.workspace, 'timeout_seconds': self.timeout_seconds,
                **({'shell': self.shell} if self.shell != 'auto' else {})}

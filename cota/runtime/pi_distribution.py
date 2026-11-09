"""Resolve the release's private runtime without downloading or modifying it."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import shutil
import tomllib


def host_platform():
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64'}.get(
        platform.machine().lower(), platform.machine().lower())
    return f'{platform.system().lower()}-{arch}'


def is_source_checkout(base_dir):
    try:
        project = tomllib.loads((base_dir.parents[1] / 'pyproject.toml').read_text())
        return project.get('project', {}).get('name') == 'cota'
    except (OSError, ValueError, IndexError):
        return False


@dataclass(frozen=True)
class PiDistribution:
    node: Path
    worker: Path
    bundled: bool


def resolve_runtime(node=None, *, base_dir=None):
    base = Path(base_dir) if base_dir is not None else Path(__file__).parent
    vendor = base / '_vendor'
    if vendor.exists():
        try:
            manifest = json.loads((vendor / 'runtime.json').read_text())
            if manifest['format'] != 1 or manifest['platform'] != host_platform():
                raise ValueError('runtime format/platform mismatch')
            for name in ('node', 'worker.mjs', 'engine.mjs', 'skills.mjs', 'tools.mjs', 'http.mjs'):
                if not (vendor / name).is_file():
                    raise ValueError(f'missing {name}')
            if not os.access(vendor / 'node', os.X_OK):
                raise ValueError('bundled node is not executable')
            for package in ('pi-agent-core', 'pi-ai', 'pi-coding-agent'):
                metadata = vendor / f'node_modules/@earendil-works/{package}/package.json'
                if json.loads(metadata.read_text())['version'] != manifest['pi_version']:
                    raise ValueError(f'{package} version mismatch')
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError(f'Invalid bundled Pi runtime ({error}); reinstall the Cota release wheel.') from error
        executable = vendor / 'node'
        worker = vendor / 'worker.mjs'
    else:
        if not is_source_checkout(base):
            raise RuntimeError('Cota runtime is missing; reinstall a supported platform release wheel.')
        worker = base / 'pi/worker.mjs'
        if not worker.is_file() or not (worker.parent / 'node_modules/@earendil-works/pi-agent-core').is_dir():
            raise RuntimeError('Source Pi dependencies missing. Run: python -m cota.runtime.pi_setup')
        executable = None
    if node is not None or executable is None:
        resolved = shutil.which(str(node or 'node'))
        if not resolved:
            raise RuntimeError('Node executable not found. Source development requires Node >= 22.19.0.')
        executable = Path(resolved)
    return PiDistribution(executable, worker, vendor.exists())

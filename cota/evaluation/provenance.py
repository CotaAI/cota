"""Source fingerprints work for installed wheels and uncommitted development code."""
import hashlib
import os
from pathlib import Path
import platform

from cota import __version__
from .schema import digest


def source_identity():
    root = Path(__file__).resolve().parents[1]
    runtime, evaluation = {}, {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(n for n in dirs if n not in ('node_modules', '_vendor', '_templates', '__pycache__', '.venv'))
        for name in sorted(files):
            file = Path(directory) / name
            relative = file.relative_to(root).as_posix()
            if name.endswith('.py') or (relative.startswith('runtime/pi/') and
                                       (name.endswith('.mjs') and not name.endswith('.test.mjs') or name in ('package.json', 'package-lock.json'))):
                target = evaluation if relative.startswith('evaluation/') else runtime
                target[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    return {'runtime_hash': digest(runtime), 'evaluation_hash': digest(evaluation),
            'cota_version': __version__, 'python_version': platform.python_version()}

"""Locate and filter official Bot templates for initialization and packaging."""
import os
from pathlib import Path
import shutil
import tomllib


TEMPLATE_IGNORE = shutil.ignore_patterns(
    '.DS_Store', 'workspace', 'evaluations', '.venv', '.cota', '__pycache__', 'node_modules', '.env', '.env.*',
    '.front_cache.html', '.front_meta.json', 'scheduler_jobs.json',
    '*.pyc', '*.log', '*.db', '*.db-*', '*.sqlite*',
)


def bot_templates_dir() -> Path:
    """Resolve installed resources or a verified checkout, never the current directory."""
    package = Path(__file__).resolve().parent
    bundled = package / '_templates' / 'bots'
    if bundled.is_dir():
        return bundled
    project = package.parent
    metadata = project / 'pyproject.toml'
    try:
        config = tomllib.loads(metadata.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        config = {}
    source = project / 'bots'
    if config.get('project', {}).get('name') == 'cota' and source.is_dir():
        return source
    raise FileNotFoundError(
        'Bot templates are missing. Reinstall the Cota release wheel, or restore '
        'the bots/ directory in your source checkout.'
    )


def template_files(root: Path):
    """Yield distributable files; directory force-includes bypass Hatch exclusions."""
    for directory, dirs, files in os.walk(root):
        ignored = TEMPLATE_IGNORE(directory, dirs + files)
        dirs[:] = sorted(name for name in dirs if name not in ignored)
        for name in sorted(files):
            if name not in ignored:
                yield Path(directory) / name

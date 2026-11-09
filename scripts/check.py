"""Run the same first-party checks locally and in CI; no provider credentials needed."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tokenize

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', '_vendor', 'workspace',
            '__pycache__', '.build', 'dist', '.omc', '.codex', '.agents',
            '.pytest_cache', '.ruff_cache', 'htmlcov'}
SUFFIXES = {'.py', '.js', '.mjs', '.sh'}


def source_files(root=ROOT):
    """Include untracked source files, excluding generated/downloaded environments."""
    for directory, dirs, files in root.walk():
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
        for name in sorted(files):
            path = directory / name
            if path.suffix in SUFFIXES:
                yield path


def run(*args):
    print('+ ' + ' '.join(str(arg) for arg in args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static-only', action='store_true', help='Syntax and Ruff only')
    parser.add_argument('--coverage', action='store_true', help='Branch coverage with the 76%% baseline gate')
    parser.add_argument('--tests', nargs='+', default=['tests'], help='Pytest files/directories/node IDs')
    args = parser.parse_args(argv)
    node = shutil.which('node')
    bash = shutil.which('bash')
    if not node or not bash:
        parser.error('Node.js >=22.19 and bash must be available on PATH')
    files = list(source_files())
    for path in files:
        if path.suffix == '.py':
            with tokenize.open(path) as source:
                ast.parse(source.read(), filename=str(path))
        else:
            command = [bash, '-n'] if path.suffix == '.sh' else [node, '--check']
            subprocess.run([*command, str(path)], cwd=ROOT, check=True)
    print(f'Syntax OK: {len(files)} first-party source files', flush=True)
    run(sys.executable, '-m', 'ruff', 'check', '.')
    if args.static_only:
        return
    pytest = [sys.executable, '-m', 'pytest', '-q', *args.tests]
    if args.coverage:
        if args.tests != ['tests']:
            parser.error('--coverage requires the complete test suite (omit --tests)')
        pytest += ['--cov=cota', '--cov-branch', '--cov-report=term-missing:skip-covered',
                   '--cov-report=json:coverage.json', '--cov-report=xml:coverage.xml',
                   '--cov-fail-under=76']
    run(*pytest)
    js_tests = [str(path.relative_to(ROOT)) for path in files
                if path.name.endswith(('.test.mjs', '.test.js'))]
    run(node, '--test', *js_tests)


if __name__ == '__main__':
    try:
        main()
    except (subprocess.CalledProcessError, SyntaxError, OSError) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        sys.exit(1)

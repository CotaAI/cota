"""Check the bundled runtime, or prepare dependencies in a source checkout."""
import argparse
from pathlib import Path
import shutil
import subprocess

from .pi_distribution import is_source_checkout, resolve_runtime


def setup(check_only=False):
    base = Path(__file__).parent
    if (base / '_vendor').exists() or not is_source_checkout(base):
        runtime = resolve_runtime()
        subprocess.run([str(runtime.node), '--input-type=module', '-e',
                        'await import(process.argv[1]);', runtime.worker.with_name('engine.mjs').as_uri()], check=True)
        return
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Pi requires Node >= 22.19.0')
    version = subprocess.run([node, '--version'], check=True, capture_output=True, text=True).stdout.strip()
    if tuple(int(p) for p in version.lstrip('v').split('.')[:3]) < (22, 19, 0):
        raise RuntimeError(f'Pi requires Node >= 22.19.0; found {version}')
    root = Path(__file__).with_name('pi')
    if not check_only:
        npm = shutil.which('npm')
        if not npm:
            raise RuntimeError('npm is required to install Pi dependencies')
        subprocess.run([npm, 'ci', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund', '--prefix', str(root)], check=True)
    subprocess.run([node, '--input-type=module', '-e',
                    'await import(process.argv[1]);', (root / 'engine.mjs').as_uri()], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check only, without downloading dependencies')
    args = parser.parse_args()
    try:
        setup(check_only=args.check)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
    print('Pi Core 1.4.0 is ready.')


if __name__ == '__main__':
    main()

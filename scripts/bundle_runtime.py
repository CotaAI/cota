"""Prepare a native, locked Pi runtime for release wheel construction (Python 3.12+)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'cota/runtime/pi'
INPUTS = ('package.json', 'package-lock.json', 'worker.mjs', 'engine.mjs', 'skills.mjs', 'tools.mjs', 'web-fetch.mjs', 'image-generate.mjs', 'image-understand.mjs', 'files.mjs', 'context.mjs', 'image-context.mjs', 'model.mjs', 'output.mjs')


def load_config():
    return json.loads((ROOT / 'scripts/node-runtime.json').read_text())


def host_platform():
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64'}.get(
        platform.machine().lower(), platform.machine().lower())
    return f'{platform.system().lower()}-{arch}'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(path, expected):
    if digest(path) != expected:
        raise ValueError(f'Node archive checksum mismatch: {path}')


def validate_bundle(path):
    """Reject stale or incomplete build inputs before producing any wheel."""
    path = Path(path)
    config = load_config()
    manifest = json.loads((path / 'runtime.json').read_text())
    target = manifest['platform']
    if target != host_platform() or target not in config['targets']:
        raise ValueError('Build and bundle platform must match; build wheels on native runners')
    expected = {key: config[key] for key in ('node_version', 'pi_version')}
    expected.update(format=1, wheel_tag=config['targets'][target]['wheel_tag'])
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError('Runtime manifest is stale; rebuild the bundle')
    for name in INPUTS:
        if digest(SOURCE / name) != manifest['inputs'][name] or digest(path / name) != manifest['inputs'][name]:
            raise ValueError(f'Runtime input changed: {name}; rebuild the bundle')
    if not os.access(path / 'node', os.X_OK) or digest(path / 'node') != manifest['node_sha256']:
        raise ValueError('Bundled Node is missing, corrupted or not executable')
    if not (path / 'NODE_LICENSE').is_file():
        raise ValueError('Missing Node license')
    for name in ('pi-agent-core', 'pi-ai', 'pi-coding-agent'):
        metadata = path / f'node_modules/@earendil-works/{name}/package.json'
        if json.loads(metadata.read_text())['version'] != config['pi_version']:
            raise ValueError(f'Unexpected {name} version')
    return manifest


def prepare(output, cache):
    config = load_config()
    target = host_platform()
    if target not in config['targets']:
        raise ValueError(f'Unsupported release platform: {target}')
    output, cache = Path(output).resolve(), Path(cache).resolve()
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a fresh build directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    version = config['node_version']
    filename = f'node-v{version}-{target}.tar.xz'
    archive = cache / filename
    if not archive.exists():
        url = f'https://nodejs.org/dist/v{version}/{filename}'
        print(f'Downloading {url}', flush=True)
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as download:
            temporary = Path(download.name)
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            verify_archive(temporary, config['targets'][target]['sha256'])
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    verify_archive(archive, config['targets'][target]['sha256'])
    with tempfile.TemporaryDirectory(prefix='cota-runtime-', dir=output.parent) as scratch:
        scratch = Path(scratch)
        with tarfile.open(archive) as package:
            package.extractall(scratch, filter='data')
        node_root = scratch / filename.removesuffix('.tar.xz')
        node = node_root / 'bin/node'
        actual = subprocess.check_output([str(node), '--version'], text=True).strip()
        if actual != f'v{version}':
            raise ValueError(f'Unexpected Node version: {actual}')
        stage = scratch / 'runtime'
        stage.mkdir()
        for name in INPUTS:
            shutil.copy2(SOURCE / name, stage / name)
        env = os.environ.copy()
        env['PATH'] = str(node.parent) + os.pathsep + env.get('PATH', '')
        subprocess.run([str(node), str(node_root / 'lib/node_modules/npm/bin/npm-cli.js'),
                        'ci', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund',
                        '--registry=https://registry.npmjs.org'],
                       cwd=stage, env=env, check=True)
        # Pi's public SDK includes optional desktop clipboard helpers. The
        # headless worker never calls them; omit these platform-native extras
        # while retaining the strict check for all other native dependencies.
        shutil.rmtree(stage / 'node_modules/@earendil-works/pi-tui/native', ignore_errors=True)
        if any((stage / 'node_modules').rglob('*.node')):
            raise ValueError('Native npm extensions need a platform compatibility audit before bundling')
        # CLI symlinks are unused by the worker and need not be shipped in a wheel.
        shutil.rmtree(stage / 'node_modules/.bin', ignore_errors=True)
        shutil.copy2(node, stage / 'node')
        shutil.copy2(node_root / 'LICENSE', stage / 'NODE_LICENSE')
        manifest = {
            'format': 1, 'platform': target, 'node_version': version,
            'pi_version': config['pi_version'], 'wheel_tag': config['targets'][target]['wheel_tag'],
            'inputs': {name: digest(SOURCE / name) for name in INPUTS},
            'node_sha256': digest(stage / 'node'),
        }
        (stage / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
        validate_bundle(stage)
        subprocess.run([str(stage / 'node'), '--input-type=module', '-e',
                        'await import(process.argv[1]);', (stage / 'engine.mjs').as_uri()], check=True)
        # Test the staged dependencies, not the developer's node_modules.
        tests = sorted(path.name for path in SOURCE.glob('*.test.mjs'))
        for test in tests:
            shutil.copy2(SOURCE / test, stage / test)
        subprocess.run([str(stage / 'node'), '--test', *(str(stage / test) for test in tests)], check=True)
        for test in tests:
            (stage / test).unlink()
        stage.rename(output)
    print(f'Prepared {output}\nBuild with COTA_RUNTIME_DIR={output} python -m build --wheel', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '.build/pi-runtime'))
    parser.add_argument('--cache', default=str(ROOT / '.build/downloads'))
    args = parser.parse_args()
    prepare(args.output, args.cache)


if __name__ == '__main__':
    main()

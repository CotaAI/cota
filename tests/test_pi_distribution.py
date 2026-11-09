import hashlib
import importlib.util
import json
from pathlib import Path
import tomllib

import pytest

from cota.runtime import pi_distribution as distribution


def bundle(tmp_path):
    root = tmp_path / 'cota' / 'runtime'
    vendor = root / '_vendor'
    vendor.mkdir(parents=True)
    (vendor / 'node').write_text('node')
    (vendor / 'node').chmod(0o755)
    (vendor / 'worker.mjs').write_text('worker')
    (vendor / 'engine.mjs').write_text('engine')
    (vendor / 'skills.mjs').write_text('skills')
    (vendor / 'tools.mjs').write_text('tools')
    (vendor / 'http.mjs').write_text('http')
    coding = vendor / 'node_modules/@earendil-works/pi-coding-agent'
    coding.mkdir(parents=True)
    (coding / 'package.json').write_text(json.dumps({'version': '1.4.0'}))
    package = vendor / 'node_modules/@earendil-works/pi-agent-core'
    package.mkdir(parents=True)
    (package / 'package.json').write_text(json.dumps({'version': '1.4.0'}))
    ai = vendor / 'node_modules/@earendil-works/pi-ai'
    ai.mkdir(parents=True)
    (ai / 'package.json').write_text(json.dumps({'version': '1.4.0'}))
    (vendor / 'runtime.json').write_text(json.dumps({
        'format': 1, 'node_version': '22.23.4', 'pi_version': '1.4.0',
        'platform': distribution.host_platform(),
    }))
    return root


def test_bundled_node_does_not_require_path(tmp_path, monkeypatch):
    root = bundle(tmp_path)
    monkeypatch.setenv('PATH', '')
    runtime = distribution.resolve_runtime(base_dir=root)
    assert runtime.node == root / '_vendor/node'
    assert runtime.worker == root / '_vendor/worker.mjs'
    assert runtime.bundled


def test_damaged_bundle_does_not_fall_back_to_system(tmp_path, monkeypatch):
    root = bundle(tmp_path)
    (root / '_vendor/node').unlink()
    monkeypatch.setattr('shutil.which', lambda _: '/system/node')
    with pytest.raises(RuntimeError, match='reinstall'):
        distribution.resolve_runtime(base_dir=root)


def test_wrong_platform_is_rejected(tmp_path, monkeypatch):
    root = bundle(tmp_path)
    monkeypatch.setattr(distribution, 'host_platform', lambda: 'wrong-platform')
    with pytest.raises(RuntimeError, match='platform'):
        distribution.resolve_runtime(base_dir=root)


def test_installed_package_without_bundle_has_no_npm_bootstrap(tmp_path):
    with pytest.raises(RuntimeError, match='release wheel'):
        distribution.resolve_runtime(base_dir=tmp_path / 'cota/runtime')


def test_source_checkout_can_use_external_node(tmp_path, monkeypatch):
    root = tmp_path / 'project/cota/runtime'
    package = root / 'pi/node_modules/@earendil-works/pi-agent-core'
    package.mkdir(parents=True)
    (root / 'pi/worker.mjs').write_text('worker')
    (tmp_path / 'project/pyproject.toml').write_text('[project]\nname="cota"\n')
    monkeypatch.setattr('shutil.which', lambda _: '/usr/local/bin/node')
    runtime = distribution.resolve_runtime(base_dir=root)
    assert runtime.node == Path('/usr/local/bin/node')
    assert not runtime.bundled


def load_builder():
    path = Path(__file__).parents[1] / 'scripts/bundle_runtime.py'
    spec = importlib.util.spec_from_file_location('bundle_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builder_targets_have_exact_checksums_and_platform_tags():
    builder = load_builder()
    targets = builder.load_config()['targets']
    assert set(targets) == {'darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64'}
    for target in targets.values():
        assert len(target['sha256']) == 64
        assert target['wheel_tag'].startswith('py3-none-')
        assert not target['wheel_tag'].endswith('-any')


def test_archive_checksum_is_checked_before_use(tmp_path):
    builder = load_builder()
    archive = tmp_path / 'node.tar.xz'
    archive.write_bytes(b'bad archive')
    with pytest.raises(ValueError, match='checksum'):
        builder.verify_archive(archive, '0' * 64)
    builder.verify_archive(archive, hashlib.sha256(b'bad archive').hexdigest())


def test_core_dependencies_match_actual_runtime():
    pyproject = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    dependencies = pyproject['project']['dependencies']
    assert any(d.startswith('loguru') for d in dependencies)
    assert not any(d.startswith(('numpy', 'cpm-kernels', 'protobuf', 'dashscope')) for d in dependencies)


def test_release_npm_lock_uses_public_registry():
    lock = json.loads((Path(__file__).parents[1] / 'cota/runtime/pi/package-lock.json').read_text())
    for package in lock['packages'].values():
        if 'resolved' in package:
            assert package['resolved'].startswith('https://registry.npmjs.org/')


def test_native_tool_adapter_is_required_in_bundle(tmp_path):
    builder = load_builder()
    assert 'tools.mjs' in builder.INPUTS
    root = bundle(tmp_path)
    (root / '_vendor/tools.mjs').unlink()
    with pytest.raises(RuntimeError, match='reinstall'):
        distribution.resolve_runtime(base_dir=root)

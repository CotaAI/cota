"""Exercise real installed-distribution discovery in an isolated interpreter."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def test_installed_channel_metadata_is_discovered_outside_checkout(tmp_path):
    root = Path(__file__).resolve().parents[2]
    example = root / 'examples' / 'channel-plugin'
    package = tomllib.loads((example / 'pyproject.toml').read_text())['project']
    installed = tmp_path / 'site-packages'
    # This is the installed wheel layout. No installer/network/build dependency
    # is required by the regression suite; actual package builds are smoke-tested separately.
    shutil.copytree(example / 'src' / 'cota_channel_example', installed / 'cota_channel_example')
    metadata = installed / 'cota_channel_example-0.1.0.dist-info'
    metadata.mkdir()
    (metadata / 'METADATA').write_text(
        f"Metadata-Version: 2.1\nName: {package['name']}\nVersion: {package['version']}\n")
    entry_points = package['entry-points']['cota.channels']
    (metadata / 'entry_points.txt').write_text('[cota.channels]\n' + '\n'.join(
        f'{name} = {factory}' for name, factory in entry_points.items()))
    source = '''
import inspect, pathlib, sys
from importlib.metadata import entry_points
from cota.channels import ChannelRegistry, MessageBus
assert any(point.name == 'example_im' for point in entry_points(group='cota.channels'))
assert 'cota_channel_example' not in sys.modules
registry = ChannelRegistry()
assert 'cota_channel_example' not in sys.modules
channel = registry.create('office_im', {'enabled': True, 'type': 'example_im'}, MessageBus())
assert channel.name == 'office_im'
assert pathlib.Path(inspect.getfile(type(channel))).is_relative_to(pathlib.Path(sys.argv[1]))
print('Installed discovery PASS')
'''
    result = subprocess.run([sys.executable, '-c', source, str(installed)], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(installed)},
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'Installed discovery PASS' in result.stdout

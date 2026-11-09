"""Release wheels must contain a validated runtime for their declared platform."""
import os
from pathlib import Path
import runpy

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class RuntimeBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != 'wheel' or version == 'editable':
            return
        templates = Path(self.root) / 'bots'
        if not (templates / 'README.md').is_file():
            raise RuntimeError('Release wheels require the bots/ template directory.')
        template_module = runpy.run_path(str(Path(self.root) / 'cota/templates.py'))
        for file in template_module['template_files'](templates):
            destination = 'cota/_templates/bots/' + file.relative_to(templates).as_posix()
            build_data['force_include'][str(file)] = destination
        runtime = os.environ.get('COTA_RUNTIME_DIR')
        if not runtime:
            raise RuntimeError('Release wheels require a bundled Pi runtime. Run scripts/bundle_runtime.py '
                               'then build with COTA_RUNTIME_DIR=<output>. For source development use pip install -e .')
        path = Path(runtime).resolve()
        builder = runpy.run_path(str(Path(self.root) / 'scripts/bundle_runtime.py'))
        manifest = builder['validate_bundle'](path)
        build_data['pure_python'] = False
        build_data['tag'] = manifest['wheel_tag']
        build_data['force_include'][str(path)] = 'cota/runtime/_vendor'

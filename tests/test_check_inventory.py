"""The check command includes new source, but never scans generated Bot state."""
from scripts.check import source_files


def test_inventory_includes_new_sources_and_prunes_generated_directories(tmp_path):
    expected = {'cota/new.py', 'tests/new.test.mjs', 'bots/weather/tools/tool.py', 'scripts/run.sh'}
    ignored = {'.venv/site.py', 'cota/runtime/_vendor/worker.mjs',
               'bots/weather/workspace/generated.py', 'node_modules/lib.js', '.git/hook.py'}
    for filename in expected | ignored:
        file = tmp_path / filename
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('')
    assert {file.relative_to(tmp_path).as_posix() for file in source_files(tmp_path)} == expected

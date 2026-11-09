"""Distributable example contracts and safe initialization."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cota import __main__ as cli
from cota.agent import Agent
from cota.llm.factory import LLMClientFactory

BOTS = Path(__file__).resolve().parents[1] / 'bots'


def test_catalog_has_maintained_examples():
    assert {p.name for p in BOTS.iterdir() if p.is_dir()} == {'weather'}
    for bot in ('weather',):
        cfg = yaml.safe_load((BOTS / bot / 'agent.yml').read_text())
        endpoints = yaml.safe_load((BOTS / bot / 'endpoints.yml').read_text())
        assert cfg['dialogue']['runtime'] == 'pi'
        assert 'actions' not in cfg
        assert all(endpoints['llms']['default'][key] == '' for key in ('key', 'apibase', 'model'))
        assert (BOTS / bot / 'README.md').is_file()


def test_init_preserves_existing_bot_and_ignores_runtime_files(tmp_path, monkeypatch):
    templates = tmp_path / 'package' / 'bots'
    source = templates / 'weather'
    source.mkdir(parents=True)
    for filename in ('agent.yml', 'endpoints.yml', 'README.md'):
        (source / filename).write_text('template')
    for dirname in ('workspace', '.venv', '__pycache__', '.cota'):
        (source / dirname).mkdir()
        (source / dirname / 'private').write_text('runtime data')
    (source / 'sessions.db').write_text('db')
    (source / '.front_cache.html').write_text('generated page')
    (source / '.front_meta.json').write_text('{}')
    (source / 'scheduler_jobs.json').write_text('[]')
    (templates / 'not-a-bot').mkdir()
    monkeypatch.setattr(cli, 'bot_templates_dir', lambda: templates)
    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    output = tmp_path / 'cota_projects' / 'weather'
    assert {p.name for p in output.iterdir()} == {'agent.yml', 'endpoints.yml', 'README.md'}
    assert not (output.parent / 'not-a-bot').exists()
    (output / 'agent.yml').write_text('my edits')
    cli.init(SimpleNamespace())
    assert (output / 'agent.yml').read_text() == 'my edits'


def test_llm_config_uses_literal_values(monkeypatch):
    monkeypatch.setenv('COTA_API_KEY', 'ignored-key')
    monkeypatch.setattr('cota.llm.factory.OpenAIClient', lambda **kwargs: kwargs)
    result = LLMClientFactory.create_client(dict(key='literal$key', model='test-model', apibase='https://model.example/v1'))
    assert result['api_key'] == 'literal$key'
    assert result['base_url'] == 'https://model.example/v1'
    assert result['model'] == 'test-model'


@pytest.mark.parametrize('field', ['key', 'apibase', 'model'])
@pytest.mark.parametrize('value', ['', '   ', None, '${MODEL_SETTING}'])
def test_unconfigured_model_fails_with_config_location(monkeypatch, field, value):
    monkeypatch.setenv('MODEL_SETTING', 'must-not-be-used')
    config = dict(key='test-key', model='test-model', apibase='https://model.example/v1')
    config[field] = value
    with pytest.raises(ValueError, match='endpoints.yml'):
        LLMClientFactory.create_client(config)


@pytest.mark.asyncio
async def test_sqlite_path_is_relative_to_bot_and_shared_with_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bot = tmp_path / 'nested' / 'bot'
    bot.mkdir(parents=True)
    (bot / 'agent.yml').write_text('system:\n  name: test\n')
    (bot / 'endpoints.yml').write_text('base_store:\n  type: sql\n  dialect: sqlite\n  db: workspace/sessions.db\n')
    agent = Agent.load_from_path(str(bot))
    try:
        agent.user_memory.set('u', 'city', 'Beijing')
        assert Path(agent.store.engine.url.database) == bot / 'workspace' / 'sessions.db'
        assert not (tmp_path / 'workspace').exists()
        from sqlalchemy import inspect
        assert 'sessions' in inspect(agent.store.engine).get_table_names()
        assert agent.user_memory.__class__.__name__ == 'SQLUserMemory'
    finally:
        await agent.cleanup()
        agent.store.engine.dispose()
        if hasattr(agent.user_memory, '_engine'):
            agent.user_memory._engine.dispose()


def test_init_copies_catalog_without_overwriting_local_readme(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    catalog = tmp_path / 'cota_projects' / 'README.md'
    assert catalog.read_text() == (BOTS / 'README.md').read_text()
    assert {p.name for p in catalog.parent.iterdir() if p.is_dir()} == {'weather'}
    catalog.write_text('local notes')
    cli.init(SimpleNamespace())
    assert catalog.read_text() == 'local notes'


def test_documented_interactive_entrypoint_dispatches_to_shell(tmp_path, monkeypatch):
    called = []
    async def shell(args):
        called.append(args.config)
    monkeypatch.setattr(cli, 'shell', shell)
    monkeypatch.setattr('sys.argv', ['cota', 'shell', '--config', str(tmp_path)])
    cli.main()
    assert called == [str(tmp_path)]


def test_template_resolution_source_is_independent_of_cwd(tmp_path, monkeypatch):
    from cota import templates
    package = tmp_path / 'source' / 'cota'
    package.mkdir(parents=True)
    root = package.parent / 'bots'
    root.mkdir()
    (package.parent / 'pyproject.toml').write_text('[project]\nname="cota"\n')
    monkeypatch.setattr(templates, '__file__', str(package / 'templates.py'))
    monkeypatch.chdir(tmp_path)
    assert templates.bot_templates_dir() == root


def test_template_resolution_installed_prefers_bundled(tmp_path, monkeypatch):
    from cota import templates
    package = tmp_path / 'site-packages' / 'cota'
    bundled = package / '_templates' / 'bots'
    bundled.mkdir(parents=True)
    (package.parent / 'bots').mkdir()
    monkeypatch.setattr(templates, '__file__', str(package / 'templates.py'))
    assert templates.bot_templates_dir() == bundled


@pytest.mark.parametrize('metadata', [None, '[project]\nname="other"\n'])
def test_template_resolution_rejects_unrelated_sibling(tmp_path, monkeypatch, metadata):
    from cota import templates
    package = tmp_path / 'cota'
    package.mkdir()
    (tmp_path / 'bots').mkdir()
    if metadata:
        (tmp_path / 'pyproject.toml').write_text(metadata)
    monkeypatch.setattr(templates, '__file__', str(package / 'templates.py'))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match='Bot templates'):
        templates.bot_templates_dir()


def test_missing_templates_does_not_create_empty_project(tmp_path, monkeypatch):
    def missing():
        raise FileNotFoundError('Bot templates are missing')
    monkeypatch.setattr(cli, 'bot_templates_dir', missing)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match='Bot templates'):
        cli.init(SimpleNamespace())
    assert not (tmp_path / 'cota_projects').exists()


def test_packaging_filter_excludes_runtime_files(tmp_path):
    from cota.templates import template_files
    expected = {'README.md', 'weather/agent.yml', 'weather/skills/demo/SKILL.md'}
    excluded = {
        '.DS_Store', 'weather/.DS_Store',
        'weather/workspace/sessions.db', 'weather/.venv/bin/python',
        'weather/__pycache__/module.pyc', 'weather/node_modules/package/index.js',
        'weather/.env', 'weather/.env.local', 'weather/a.db-wal', 'weather/a.sqlite3',
        'weather/session.log', 'weather/.front_cache.html', 'weather/.front_meta.json',
        'weather/scheduler_jobs.json',
        'weather/.cota/web.key', 'weather/.cota/chat.sqlite3',
    }
    for name in expected | excluded:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture')
    assert {f.relative_to(tmp_path).as_posix() for f in template_files(tmp_path)} == expected


def test_weather_activity_catalog_survives_init_and_packaging(tmp_path, monkeypatch):
    import json
    from cota.templates import template_files
    source = BOTS / 'weather' / 'skills' / 'activity-search' / 'activities.json'
    data = json.loads(source.read_text())
    assert 'mock' not in data and data['currency'] == 'CNY'
    assert all('模拟' not in a['name'] for a in data['activities'])
    activities = data['activities']
    assert len({a['id'] for a in activities}) == len(activities)
    assert {'杭州', '上海', '北京'} <= {a['city'] for a in activities}
    assert {True, False} == {a['indoor'] for a in activities}
    assert any(not a['available'] for a in activities)
    assert any(a['price_per_person'] is None for a in activities)
    assert source in set(template_files(BOTS))
    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    target = tmp_path / 'cota_projects' / 'weather' / 'skills' / 'activity-search' / 'activities.json'
    assert target.read_bytes() == source.read_bytes()


def test_init_keeps_user_projects_from_removed_templates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / 'cota_projects' / 'pet'
    existing.mkdir(parents=True)
    (existing / 'agent.yml').write_text('user-owned bot')
    cli.init(SimpleNamespace())
    assert (existing / 'agent.yml').read_text() == 'user-owned bot'
    assert (existing.parent / 'weather' / 'agent.yml').is_file()
    assert not (existing.parent / 'hello').exists()

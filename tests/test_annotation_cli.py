import asyncio
from unittest.mock import patch
import pytest
import yaml
from cota.__main__ import create_argument_parser
from cota.annotation_files import read_worksheet
from cota.policy import PolicyCatalog
from cota.store import SQLStore
from tests.test_annotation_worksheet import conversation
from tests.test_skill_policy import result_policy as policy


@pytest.fixture
def bot(tmp_path):
    (tmp_path / 'agent.yml').write_text('policy: {max_policies: 8, max_chars: 12000}\n')
    (tmp_path / 'endpoints.yml').write_text('base_store: {type: sql, dialect: sqlite, db: conversations.db}\n')
    return tmp_path


async def seed(bot):
    store = SQLStore(db=str(bot / 'conversations.db'))
    await store.save(conversation())
    store.engine.dispose()


def invoke(*args):
    parsed = create_argument_parser().parse_args(list(args))
    parsed.func(parsed)


def test_cli_export_edit_import_without_loading_agent(bot, capsys):
    asyncio.run(seed(bot))
    source, target = bot / 'review.yml', bot / 'reviewed.yml'
    with patch('cota.agent.Agent.load_from_path', side_effect=AssertionError('Must not initialize an agent')):
        invoke('annotate', 'export', '--config', str(bot), '--session', 'conversation', '--output', str(source))
        assert not (bot / 'review.yml.source.json').exists()
        assert set(read_worksheet(source)) == {'policies'}
        source.write_text(yaml.safe_dump({'policies': [policy()]}, allow_unicode=True))
        with patch('cota.store.Store.create', side_effect=AssertionError('Import must not connect Store')):
            invoke('annotate', 'import', '--config', str(bot), '--input', str(source), '--output', str(target))
    assert PolicyCatalog.load(target).policies == [policy()]
    assert '重新加载' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        invoke('annotate', 'import', '--config', str(bot), '--input', str(source), '--output', str(target))


def test_handwritten_cli_does_not_connect_store(bot):
    source, target = bot / 'manual.yml', bot / 'checked.yml'
    source.write_text(yaml.safe_dump({'policies': [policy()]}))
    with patch('cota.store.Store.create', side_effect=AssertionError('Handwritten Policy needs no Store')):
        invoke('annotate', 'import', '--config', str(bot), '--input', str(source), '--output', str(target))
    assert PolicyCatalog.load(target).policies == [policy()]


def test_cli_memory_export_error_explains_live_store_alternative(bot, capsys):
    (bot / 'endpoints.yml').write_text('base_store: {type: memory}\n')
    with pytest.raises(SystemExit):
        invoke('annotate', 'export', '--config', str(bot), '--session', 's', '--output', str(bot / 'out.yml'))
    assert '内存' in capsys.readouterr().err


def test_invalid_import_no_policy_output(bot):
    source, target = bot / 'bad.yml', bot / 'output.yml'
    source.write_text('policies:\n- name: bad\n  steps: []\n')
    with pytest.raises(SystemExit):
        invoke('annotate', 'import', '--config', str(bot), '--input', str(source), '--output', str(target))
    assert not target.exists()


def test_missing_session_does_not_create_output(bot, capsys):
    asyncio.run(seed(bot))
    target = bot / 'missing.yml'
    with pytest.raises(SystemExit):
        invoke('annotate', 'export', '--config', str(bot), '--session', 'missing', '--output', str(target))
    assert '会话不存在' in capsys.readouterr().err
    assert not target.exists()


def test_export_and_import_leave_database_unchanged(bot):
    asyncio.run(seed(bot))
    async def snapshot():
        store = SQLStore(db=str(bot / 'conversations.db'))
        try:
            return await store.export_session('conversation')
        finally:
            store.engine.dispose()
    before = asyncio.run(snapshot())
    source, target = bot / 'source.yml', bot / 'policy.yml'
    invoke('annotate', 'export', '--config', str(bot), '--session', 'conversation', '--output', str(source))
    source.write_text(yaml.safe_dump({'policies': [policy()]}))
    invoke('annotate', 'import', '--config', str(bot), '--input', str(source), '--output', str(target))
    assert asyncio.run(snapshot()) == before

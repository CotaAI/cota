"""Project-scoped production accounting; no provider or Cota runtime required."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

BOT = Path(__file__).resolve().parents[1] / 'bots/picture-book'


@pytest.fixture
def production(monkeypatch):
    monkeypatch.syspath_prepend(str(BOT))
    return importlib.import_module('bookbot.production')


def journal(project, name, *, asset='page-04', status='completed', **fields):
    path = project / f'{name}.request.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'asset': asset, 'status': status, 'output': f'{name}.png', **fields}))
    return path


def test_three_generation_attempts_survive_new_objects_and_output_names(production, tmp_path):
    for attempt in range(3):
        with production.Production(tmp_path, 'page-04') as task:
            assert task.check_generation() == attempt + 1
            journal(tmp_path, f'version-{attempt}', attempt=attempt + 1)
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.check_generation()
        assert error.value.details['reason'] == 'revision_limit_reached'
        assert error.value.details['asset'] == 'page-04'
        assert error.value.details['retryable'] is False
    with production.Production(tmp_path, 'cover') as task:
        assert task.check_generation() == 1


def test_unknown_outcome_blocks_changed_filenames_and_aliases_are_not_attempts(production, tmp_path):
    journal(tmp_path, 'first')
    journal(tmp_path, 'copy', reused_from='first.png')
    with production.Production(tmp_path, 'page-04') as task:
        assert task.check_generation() == 2
        assert len(task.generations) == 1
    journal(tmp_path, 'unknown', status='started')
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.check_generation()
        assert error.value.details['reason'] == 'prior_outcome_unknown'


@pytest.mark.parametrize('asset', ['', '../page', '/tmp/page', 'page/04', 'page.04', 1, 'x' * 81])
def test_asset_identity_is_confined_before_any_lock_or_metadata(production, tmp_path, asset):
    with pytest.raises(ValueError, match='asset'):
        production.Production(tmp_path, asset)
    assert not list(tmp_path.iterdir())


def test_criteria_are_stable_and_bound_to_asset_not_filename(production, tmp_path):
    with production.Production(tmp_path, 'page-04') as task:
        task.bind_criteria('Keep the two visible gripper teeth.\n')
        task.bind_criteria('Keep the two visible gripper teeth.\n')
        with pytest.raises(production.ProductionBlocked) as error:
            task.bind_criteria('Round hands are fine.')
        assert error.value.details['reason'] == 'review_criteria_changed'
        assert error.value.details['retryable'] is False
    with production.Production(tmp_path, 'cover') as task:
        task.bind_criteria('Round hands are fine.')
    record = json.loads((tmp_path / '.bookbot/assets/page-04.json').read_text())
    assert record['criteria'].strip() == 'Keep the two visible gripper teeth.'


def test_review_paths_are_scoped_and_do_not_create_reports(production, tmp_path):
    with production.Production(tmp_path, 'page-04') as task:
        path = task.review_path('a' * 64)
        assert path == tmp_path / '.bookbot/reviews/page-04' / ('a' * 64 + '.json')
        assert not path.exists()
        with pytest.raises(ValueError):
            task.review_path('../../elsewhere')


def test_lock_is_nonblocking_and_released_after_errors(production, tmp_path):
    with pytest.raises(RuntimeError, match='leave command'):
        with production.Production(tmp_path, 'page-04'):
            with pytest.raises(production.ProductionBlocked) as error:
                with production.Production(tmp_path, 'cover'):
                    pytest.fail('Concurrent production entered')
            assert error.value.details['reason'] == 'production_in_progress'
            raise RuntimeError('leave command')
    with production.Production(tmp_path, 'cover') as task:
        assert task.check_generation() == 1


def test_lock_is_released_when_an_owner_process_exits(production, tmp_path):
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from bookbot.production import Production
p = Production(sys.argv[2], 'page-04')
p.__enter__()
print('locked', flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', code, str(BOT), str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(production.ProductionBlocked):
            with production.Production(tmp_path, 'cover'):
                pytest.fail('Concurrent process entered')
    finally:
        child.terminate()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
    with production.Production(tmp_path, 'cover'):
        pass


def test_status_uses_journals_without_mutating_files(production, tmp_path):
    journal(tmp_path, 'page-04-first')
    journal(tmp_path, 'page-04-second')
    journal(tmp_path, 'cover', asset='cover', status='started')
    legacy = journal(tmp_path, 'legacy')
    legacy.write_text(json.dumps({'status': 'completed', 'output': 'legacy.png'}))
    journal(tmp_path, 'review', asset='page-04', kind='review', status='started')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    status = production.production_status(tmp_path)
    assert status['assets']['page-04']['attempts'] == 2
    assert status['assets']['page-04']['remaining_generations'] == 1
    assert status['assets']['page-04']['latest_output'] == 'page-04-second.png'
    assert status['assets']['cover']['blocked_reason'] == 'prior_outcome_unknown'
    assert status['untracked_requests'] == ['legacy.request.json']
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_corrupt_journal_or_metadata_never_resets_the_budget(production, tmp_path):
    bad = tmp_path / 'bad.request.json'
    bad.write_text('{"incomplete":')
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.check_generation()
        assert error.value.details['reason'] == 'production_history_invalid'
    bad.unlink()
    with production.Production(tmp_path, 'page-04') as task:
        task.bind_criteria('Keep the teeth.')
    (tmp_path / '.bookbot/assets/page-04.json').write_text('{}')
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.bind_criteria('Different criteria.')
        assert error.value.details['reason'] == 'production_history_invalid'


def test_project_metadata_symlinks_do_not_escape(production, tmp_path):
    project, outside = tmp_path / 'project', tmp_path / 'outside'
    project.mkdir()
    outside.mkdir()
    (project / '.bookbot').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='Symlinks'):
        with production.Production(project, 'page-04'):
            pass
    assert not list(outside.iterdir())


@pytest.mark.parametrize('field,value', [('attempt', 'one'), ('attempt', 0), ('started_at', 'later'),
                                         ('started_at', float('nan'))])
def test_invalid_order_metadata_reports_unknown_history_without_traceback(production, tmp_path, field, value):
    journal(tmp_path, 'first', **{field: value})
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.check_generation()
        assert error.value.details['reason'] == 'production_history_invalid'
    with pytest.raises(production.ProductionBlocked):
        production.production_status(tmp_path)


def test_missing_criteria_cannot_rebind_after_a_review_was_recorded(production, tmp_path):
    with production.Production(tmp_path, 'page-04') as task:
        task.bind_criteria('Keep the teeth.')
        path = task.review_path('b' * 64)
        path.parent.mkdir(parents=True)
        path.write_text('{"content":"An existing observation"}')
    (tmp_path / '.bookbot/assets/page-04.json').unlink()
    with production.Production(tmp_path, 'page-04') as task:
        with pytest.raises(production.ProductionBlocked) as error:
            task.bind_criteria('Change the criteria.')
        assert error.value.details['reason'] == 'production_history_invalid'

import pytest
from cota.annotation_files import export_worksheet, write_worksheet, read_worksheet
from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent
from cota.store import MemoryStore
from tests.resource_fixtures import skill_result
from tests.test_skill_policy import result_policy


def conversation():
    dst = DST('conversation', None)
    for number, text in enumerate(['查一下天气', '北京']):
        user = UserUtterEvent(text)
        dst.append_event(user)
        run = f'run-{number}'
        dst.append_event(Event('run_started', {'input_event_id': user.event_id}, run_id=run))
        dst.append_event(skill_result('weather', run_id=run))
        dst.append_event(BotUtterEvent(['哪个城市？', '北京今天晴。'][number], run_id=run))
        dst.append_event(Event('run_finished', {'status': 'completed'}, run_id=run))
    return dst



def test_export_is_editable_dialogue_without_invented_business_steps(tmp_path):
    dst = conversation()
    before = dst.as_dict()
    doc = export_worksheet(dst)
    assert set(doc) == {'policies'}
    assert doc['policies'][0]['steps'] == [
        {'user': '查一下天气'}, {'bot': [{'reply': '哪个城市？'}]},
        {'user': '北京'}, {'bot': [{'reply': '北京今天晴。'}]},
    ]
    path = tmp_path / 'review.yml'
    write_worksheet(path, doc)
    assert read_worksheet(path) == doc
    assert list(tmp_path.iterdir()) == [path]
    assert dst.as_dict() == before
    with pytest.raises(FileExistsError):
        write_worksheet(path, {'policies': []})
    assert read_worksheet(path) == doc


def test_handwritten_file_needs_no_store(tmp_path):
    path = tmp_path / 'manual.yml'
    document = {'policies': [result_policy()]}
    write_worksheet(path, document)
    assert read_worksheet(path) == document
    assert 'result 写示例结果条件' in path.read_text()


@pytest.mark.asyncio
async def test_edit_and_write_policy_never_changes_source_session(tmp_path):
    store = MemoryStore()
    dst = conversation()
    await store.save(dst)
    before = await store.export_session(dst.session_id)
    original = export_worksheet(dst)
    document = export_worksheet(dst)
    document['policies'][0]['steps'][1]['bot'] = result_policy()['steps'][1]['bot']
    path = tmp_path / 'reviewed.yml'
    write_worksheet(path, document)
    assert read_worksheet(path) == document
    restored = await store.load(dst.session_id)
    assert restored.as_dict() == before
    assert export_worksheet(restored) == original
    assert 'policy_annotations' not in restored.trace('run-0')


@pytest.mark.parametrize('text', [
    'policies: []\npolicies: []\n',
    'schema_version: 1\nannotations: {}\nconversation: []\n',
    'policies: []\n',
])
def test_invalid_or_empty_worksheet_fails(tmp_path, text):
    path = tmp_path / 'bad.yml'
    path.write_text(text)
    with pytest.raises(ValueError):
        read_worksheet(path)


def test_write_failure_removes_new_partial_file(tmp_path, monkeypatch):
    path = tmp_path / 'review.yml'
    from pathlib import Path
    from contextlib import contextmanager
    original = Path.open
    @contextmanager
    def failing_open(self, *args, **kwargs):
        with original(self, *args, **kwargs) as output:
            class BrokenOutput:
                def write(self, text):
                    output.write(text[:10])
                    raise OSError('disk full')
            yield BrokenOutput()
    monkeypatch.setattr(Path, 'open', failing_open)
    with pytest.raises(OSError, match='disk full'):
        write_worksheet(path, export_worksheet(conversation()))
    assert not path.exists()

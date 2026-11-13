"""Native image-understanding evidence, without paid requests or live Bot data."""
import importlib
import json
import sqlite3

import pytest
import yaml

from tests.test_picture_book_bot import book_modules as book_modules, book_root as book_root, image_bytes


@pytest.fixture
def native_review(book_modules, book_root):
    root, project = book_root
    common = book_modules['common']
    image = project / 'previews/pages/page-1.png'
    image.parent.mkdir(parents=True)
    image.write_bytes(image_bytes())
    prompt = '1. Text is readable. Return JSON with verdict and checks (id, status, evidence).'
    (project / 'criteria.txt').write_text(prompt)
    (project / 'book.json').write_text(json.dumps({'pages': [{'page': 1}]}))
    endpoints = yaml.safe_load((root / 'endpoints.yml').read_text())
    endpoints['base_store'] = {'type': 'sql', 'dialect': 'sqlite', 'db': 'workspace/sessions.db'}
    endpoints['llms'] = {'image-understanding': {'type': 'openai', 'key': 'TEST_ONLY',
                                               'apibase': 'https://vision.example/v1', 'model': 'vision-model'}}
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    db = root / 'workspace/sessions.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE events(session_id TEXT, sequence INTEGER, event_id TEXT, run_id TEXT, type TEXT, payload TEXT)')
    start = {'tool': 'image_understand', 'tool_call_id': 'vision-call',
             'arguments': {'image_path': str(image), 'prompt': prompt}}
    result = {'tool': 'image_understand', 'tool_call_id': 'vision-call', 'status': 'success',
              'result': {'model': 'vision-model', 'image_path': str(image), 'image_sha256': common.sha256(image.read_bytes())},
              'content': [{'type': 'text', 'text': json.dumps({'verdict': 'pass', 'checks': [
                  {'id': '1', 'status': 'pass', 'evidence': 'All text is visible.'}]})}]}
    for seq, kind, data in [(1, 'tool_started', start), (2, 'tool_result', result)]:
        conn.execute('INSERT INTO events VALUES(?,?,?,?,?,?)', ('session-a', seq, f'event-{seq}', 'run-a', kind, json.dumps(data)))
    conn.commit()
    conn.close()
    return root, project, db


def update_result(db, change):
    with sqlite3.connect(db) as conn:
        payload = json.loads(conn.execute('SELECT payload FROM events WHERE sequence=2').fetchone()[0])
        change(payload)
        conn.execute('UPDATE events SET payload=? WHERE sequence=2', (json.dumps(payload),))


def record_review(native_review):
    root, project, _ = native_review
    return importlib.import_module('bookbot.tool_reviews').record_review(
        root, project, 'criteria.txt', ['previews/pages/page-1.png'], 'reviews/page-1.json',
        asset='pdf-face-01', tool_call_id='vision-call')


def test_native_review_imports_committed_observation_and_reuses_it(native_review):
    root, project, db = native_review
    before = db.read_bytes()
    report = record_review(native_review)
    assert report['assessment']['verdict'] == 'pass'
    assert report['source'] == {'tool': 'image_understand', 'session_id': 'session-a', 'run_id': 'run-a',
                                'tool_call_id': 'vision-call', 'event_id': 'event-2'}
    assert record_review(native_review)['reused'] is True
    assert db.read_bytes() == before
    render = importlib.import_module('bookbot.render_state')
    assert render.accepted_review(project, 1, report['image_inputs'][0]['sha256'])
    importlib.import_module('bookbot.tool_reviews').require_visual_reviews(project)


@pytest.mark.parametrize('invalid', ['read', 'failed', 'wrong_image', 'wrong_prompt', 'wrong_model', 'wrong_run', 'missing_result'])
def test_rejects_invalid_native_review_evidence(native_review, invalid):
    root, project, db = native_review
    if invalid == 'read':
        with sqlite3.connect(db) as conn:
            for seq, raw in conn.execute('SELECT sequence,payload FROM events').fetchall():
                data = json.loads(raw); data['tool'] = 'read'
                conn.execute('UPDATE events SET payload=? WHERE sequence=?', (json.dumps(data), seq))
    elif invalid == 'failed':
        update_result(db, lambda d: d.update(status='error'))
    elif invalid == 'wrong_image':
        (project / 'previews/pages/page-1.png').write_bytes(b'changed')
    elif invalid == 'wrong_prompt':
        (project / 'criteria.txt').write_text('1. Different criteria.')
    elif invalid == 'wrong_model':
        update_result(db, lambda d: d['result'].update(model='another-model'))
    elif invalid == 'wrong_run':
        with sqlite3.connect(db) as conn: conn.execute("UPDATE events SET run_id='other' WHERE sequence=2")
    elif invalid == 'missing_result':
        with sqlite3.connect(db) as conn: conn.execute('DELETE FROM events WHERE sequence=2')
    with pytest.raises(ValueError): record_review(native_review)
    assert not (project / 'reviews/page-1.json').exists()


def test_unstructured_observation_and_changed_image_cannot_approve_page(native_review):
    _, project, db = native_review
    update_result(db, lambda d: d.update(content=[{'type': 'text', 'text': 'Looks perfect.'}]))
    assert record_review(native_review)['assessment']['verdict'] == 'uncertain'
    reviews = importlib.import_module('bookbot.tool_reviews')
    with pytest.raises(ValueError, match='visual review'): reviews.require_visual_reviews(project)


def test_final_validation_rejects_read_or_manual_qa_flags(native_review):
    _, project, _ = native_review
    data = json.loads((project / 'book.json').read_text()); data['qa'] = {'pdf_rendered_reviewed': True}
    (project / 'book.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='visual review'):
        importlib.import_module('bookbot.tool_reviews').require_visual_reviews(project)


def test_changed_pixels_invalidate_previous_native_review(native_review):
    _, project, _ = native_review
    record_review(native_review)
    (project / 'previews/pages/page-1.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='visual review'):
        importlib.import_module('bookbot.tool_reviews').require_visual_reviews(project)


def test_byte_identical_alias_preserves_original_tool_input(native_review):
    root, project, _ = native_review
    record_review(native_review)
    (project / 'alias.png').write_bytes((project / 'previews/pages/page-1.png').read_bytes())
    result = importlib.import_module('bookbot.tool_reviews').record_review(
        root, project, 'criteria.txt', ['alias.png'], 'alias-review.json',
        asset='pdf-face-01', tool_call_id='vision-call')
    assert result['reused'] is True
    assert result['image_inputs'][0]['path'] == 'previews/pages/page-1.png'
    assert result['current_image_inputs'][0]['path'] == 'alias.png'

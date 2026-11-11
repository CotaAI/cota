"""Regressions for truthful layout/review results; no paid model requests."""
import importlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

import httpx
import pytest
import yaml

BOT = Path(__file__).resolve().parents[1] / 'bots/picture-book'


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(BOT))
    layout = importlib.import_module('bookbot.layout')
    models = importlib.import_module('bookbot.models')
    root = tmp_path / 'bot'
    project = root / 'workspace/books/example'
    project.mkdir(parents=True)
    (root / 'endpoints.yml').write_text(yaml.safe_dump({'picture_book': {
        'vision': {'key': 'TEST_ONLY', 'apibase': 'https://vision.example/v1', 'model': 'vision'},
    }}))
    data = {'title': 'Example', 'page_count': 2,
            'format': {'width_mm': 210, 'height_mm': 148},
            'pages': [{'page': 1, 'role': 'cover', 'text_elements': [
                {'text': 'Hello', 'box': [10, 10, 150, 30], 'font_size': 18}]},
                      {'page': 2, 'role': 'back-cover', 'blank': True}],
            'qa': {'pdf_rendered_reviewed': False}}
    return layout, models, root, project, data


def manifest(project, data):
    (project / 'book.json').write_text(json.dumps(data))


def renderer(layout, root):
    pytest.importorskip('PIL')
    pytest.importorskip('pypdf')
    pytest.importorskip('reportlab')
    if not shutil.which('pdftoppm'):
        pytest.skip('Optional PDF checks require Poppler')
    try:
        layout.font_path(root)
    except ValueError:
        pytest.skip('Optional PDF checks require a TrueType font')


@pytest.mark.parametrize('field,value', [('image_path', 'other.png'), ('font_size', 22)])
def test_unknown_page_fields_fail_before_creating_outputs(book, field, value):
    layout, _, root, project, data = book
    renderer(layout, root)
    data['pages'][0][field] = value
    manifest(project, data)
    with pytest.raises(ValueError, match=field):
        layout.build(root, project)
    assert not (project / 'book.pdf').exists()


@pytest.mark.parametrize('field,value', [('weight', 'bold'), ('align', 'diagonal'),
                                        ('fill', 'reddish'), ('font_size', 0),
                                        ('text', None)])
def test_invalid_text_settings_are_not_silently_ignored(book, field, value):
    layout, _, root, project, data = book
    renderer(layout, root)
    data['pages'][0]['text_elements'][0][field] = value
    manifest(project, data)
    with pytest.raises(ValueError, match=field):
        layout.build(root, project)
    assert not (project / 'book.pdf').exists()


@pytest.mark.parametrize('align,min_x,max_x', [('left', 28, 29), ('center', 180, 300), ('right', 300, 454)])
def test_alignment_and_colour_reach_the_pdf(book, align, min_x, max_x):
    layout, _, root, project, data = book
    renderer(layout, root)
    from pypdf import PdfReader
    data['pages'][0]['text_elements'][0].update(align=align, fill='#ff0000')
    manifest(project, data)
    result = layout.build(root, project)
    page = PdfReader(project / 'book.pdf').pages[0]
    positions = []
    page.extract_text(visitor_text=lambda text, cm, tm, font, size: positions.append(tm[4]) if 'Hello' in text else None)
    assert positions and min_x < positions[0] < max_x
    assert b'1 0 0 rg' in page.get_contents().get_data()
    assert result['reused'] is False
    assert result['input_hash'] == json.loads((project / 'book.json').read_text())['render_input_hash']
    # A rejected edit must preserve the previous PDF and previews exactly.
    old_pdf = (project / 'book.pdf').read_bytes()
    old_preview = (project / 'previews/overview.jpg').read_bytes()
    data['pages'][0]['image_path'] = 'ignored.png'
    manifest(project, data)
    with pytest.raises(ValueError, match='image_path'):
        layout.build(root, project)
    assert (project / 'book.pdf').read_bytes() == old_pdf
    assert (project / 'previews/overview.jpg').read_bytes() == old_preview


def test_unchanged_build_reuses_outputs_but_checks_integrity(book, monkeypatch):
    layout, _, root, project, data = book
    renderer(layout, root)
    manifest(project, data)
    layout.build(root, project)
    data = json.loads((project / 'book.json').read_text())
    data['qa']['pdf_rendered_reviewed'] = True
    manifest(project, data)
    before = (project / 'book.pdf').stat().st_mtime_ns
    original = layout.subprocess.run
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(layout.subprocess, 'run', run)
    assert layout.build(root, project)['reused'] is True
    assert not calls and (project / 'book.pdf').stat().st_mtime_ns == before
    (project / 'previews/overview.jpg').write_bytes(b'damaged')
    assert layout.build(root, project)['reused'] is False
    assert calls
    assert json.loads((project / 'book.json').read_text())['qa']['pdf_rendered_reviewed'] is False
    # Per-page previews are also evidence, not an unchecked cache.
    (project / 'previews/pages/page-1.png').write_bytes(b'damaged page')
    with pytest.raises(ValueError, match='rebuild'):
        layout.require_current_render(root, project)


def png():
    Image = pytest.importorskip('PIL.Image')
    buffer = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(buffer, format='PNG')
    return buffer.getvalue()


def test_review_labels_match_image_order_and_saved_versions(book):
    _, models, root, project, _ = book
    (project / 'prompt.txt').write_text('Check page 7 against the character reference.')
    (project / 'page-07.png').write_bytes(png())
    (project / 'character.png').write_bytes(png())
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'A specific observation.'}}]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = models.review(root, project, 'prompt.txt', ['page-07.png', 'character.png'], 'review.json', client=client)
        assert report['image_inputs'][0]['path'] == 'page-07.png'
        assert report['image_inputs'][1]['path'] == 'character.png'
        content = bodies[0]['messages'][0]['content']
        assert 'page-07.png' in content[1]['text'] and content[2]['type'] == 'image_url'
        assert 'character.png' in content[3]['text'] and content[4]['type'] == 'image_url'
        assert report['image_inputs'][0]['sha256'] in content[1]['text']
        assert models.review(root, project, 'prompt.txt', ['page-07.png', 'character.png'],
                             'review.json', client=client)['reused'] is True
        # Same pixels under different names must not reuse a report with stale labels.
        (project / 'other.png').write_bytes(png())
        with pytest.raises(ValueError, match='already exists'):
            models.review(root, project, 'prompt.txt', ['other.png', 'character.png'], 'review.json', client=client)
    assert len(bodies) == 1
    assert 'TEST_ONLY' not in (project / 'review.json').read_text()


def test_review_rejects_empty_instructions_before_model_request(book):
    _, models, root, project, _ = book
    (project / 'prompt.txt').write_text('   ')
    (project / 'page.png').write_bytes(png())
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('No paid request'))) as client:
        with pytest.raises(ValueError, match='prompt'):
            models.review(root, project, 'prompt.txt', ['page.png'], 'review.json', client=client)


def test_cli_returns_nonzero_for_unsupported_layout(book):
    layout, _, root, project, data = book
    renderer(layout, root)
    shutil.copytree(BOT / 'bookbot', root / 'bookbot', ignore=shutil.ignore_patterns('__pycache__'))
    (root / 'scripts').mkdir()
    shutil.copy(BOT / 'scripts/book.py', root / 'scripts/book.py')
    data['pages'][0]['image_path'] = 'ignored.png'
    manifest(project, data)
    result = subprocess.run([sys.executable, str(root / 'scripts/book.py'), '--project', 'example', 'build'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'image_path' in json.loads(result.stderr)['error']
    assert not result.stdout

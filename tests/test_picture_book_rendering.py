"""Local rendering/revision regressions; no model services or live Bot files."""
import importlib
import json
from pathlib import Path
import shutil

import pytest

BOT = Path(__file__).resolve().parents[1] / 'bots/picture-book'


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(BOT))
    layout = importlib.import_module('bookbot.layout')
    pytest.importorskip('PIL')
    pytest.importorskip('pypdf')
    pytest.importorskip('reportlab')
    if not shutil.which('pdftoppm'):
        pytest.skip('Poppler required')
    root = tmp_path / 'bot'
    project = root / 'workspace/books/example'
    project.mkdir(parents=True)
    (root / 'endpoints.yml').write_text('{}')
    try:
        layout.font_path(root)
    except ValueError:
        pytest.skip('Embeddable font required')
    from PIL import Image
    Image.new('RGB', (800, 200), 'red').save(project / 'art.png')
    data = {'title': 'Example', 'page_count': 2,
            'format': {'width_mm': 120, 'height_mm': 100},
            'printing': {'sheets': 1},
            'pages': [{'page': 1, 'role': 'cover', 'asset': 'art.png', 'image_box': [0, 0, 120, 100]},
                      {'page': 2, 'role': 'back-cover', 'blank': True}],
            'qa': {'story_reviewed': False, 'language_reviewed': False,
                   'visual_continuity_reviewed': False, 'pdf_rendered_reviewed': False, 'print_tested': False}}
    save(project, data)
    return layout, root, project, data


def save(project, data):
    (project / 'book.json').write_text(json.dumps(data))


def load(project):
    return json.loads((project / 'book.json').read_text())


def test_cover_and_contain_are_explicit_deterministic_geometry(book):
    from PIL import Image
    layout, root, project, data = book
    data['pages'][0]['image_fit'] = 'cover'
    save(project, data)
    layout.build(root, project)
    with Image.open(project / 'previews/pages/page-1.png') as image:
        colour = image.convert('RGB').getpixel((10, 10))
        assert colour[0] > 240 and colour[1] < 20
    data = load(project)
    data['pages'][0]['image_fit'] = 'contain'
    save(project, data)
    layout.build(root, project)
    with Image.open(project / 'previews/pages/page-1.png') as image:
        assert min(image.convert('RGB').getpixel((10, 10))) > 240


def test_printing_profile_change_only_invalidates_physical_proof(book):
    layout, root, project, _ = book
    layout.build(root, project)
    data = load(project)
    data['qa'] = {key: True for key in data['qa']}
    data['print_status'] = 'physical-proof-passed'
    data['printing']['profile'] = 'separate-covers-title'
    save(project, data)
    result = layout.build(root, project)
    assert result['reused'] and result['rendered_pages'] == 0
    assert result['invalidated_checks'] == ['print_tested']
    updated = load(project)
    assert not updated['qa']['print_tested']
    assert updated['print_status'] == 'pending-physical-proof'
    assert all(value for key, value in updated['qa'].items() if key != 'print_tested')
    assert layout.render_status(project)['pages']['1']['versions'] == 1


def test_metadata_change_preserves_pdf_previews_qa_and_revision_budget(book, monkeypatch):
    layout, root, project, _ = book
    layout.build(root, project)
    data = load(project)
    data['qa'].update({key: True for key in data['qa']})
    data['pages'][0].update(notes='Editorial note', layout='full-bleed-with-negative-space')
    data['printing']['sheets'] = 99
    save(project, data)
    pdf = (project / 'book.pdf').read_bytes()
    preview = (project / 'previews/pages/page-1.png').read_bytes()
    def no_render(*args, **kwargs):
        pytest.fail('Metadata must not rerender')
    monkeypatch.setattr(layout.subprocess, 'run', no_render)
    result = layout.build(root, project)
    assert result['reused'] is True and result['changed_pages'] == []
    assert (project / 'book.pdf').read_bytes() == pdf
    assert (project / 'previews/pages/page-1.png').read_bytes() == preview
    assert load(project)['qa'] == data['qa']
    assert load(project)['printing']['sheets'] == 1
    layout.require_current_render(root, project)
    from bookbot.render_state import render_status
    assert render_status(project)['pages']['1']['versions'] == 1


def test_page_edits_are_bounded_across_builds_and_preserve_previous_package(book):
    layout, root, project, _ = book
    for number in range(3):
        data = load(project)
        data['pages'][0]['text_elements'] = [{'text': f'Revision {number}', 'box': [10, 10, 100, 20], 'font_size': 12}]
        save(project, data)
        result = layout.build(root, project)
        assert result['changed_pages'] == [1] if number else result['changed_pages'] == [1, 2]
    before = (project / 'book.pdf').read_bytes()
    previews = (project / 'previews/pages/page-1.png').read_bytes()
    data = load(project)
    data['pages'][0]['text_elements'][0]['text'] = 'Fourth version'
    save(project, data)
    with pytest.raises(ValueError) as blocked:
        layout.build(root, project)
    assert blocked.value.details['reason'] == 'page_revision_limit_reached'
    assert (project / 'book.pdf').read_bytes() == before
    assert (project / 'previews/pages/page-1.png').read_bytes() == previews


def test_unchanged_and_repaired_outputs_do_not_spend_a_revision(book):
    layout, root, project, _ = book
    layout.build(root, project)
    assert layout.build(root, project)['reused'] is True
    (project / 'previews/pages/page-1.png').write_bytes(b'damaged')
    result = layout.build(root, project)
    assert result['changed_pages'] == []
    from bookbot.render_state import render_status
    assert render_status(project)['pages']['1']['versions'] == 1
    assert load(project)['qa']['pdf_rendered_reviewed'] is False


def test_accepted_exact_version_is_frozen_without_guessing_free_text(book):
    from bookbot.common import sha256
    layout, root, project, _ = book
    layout.build(root, project)
    preview = (project / 'previews/pages/page-1.png').read_bytes()
    folder = project / '.bookbot/reviews/pdf-face-01'
    folder.mkdir(parents=True)
    record = {'asset': 'pdf-face-01', 'input_hash': 'a'*64,
              'image_inputs': [{'role': 'target', 'sha256': sha256(preview)}],
              'assessment': {'verdict': 'pass', 'checks': [
                  {'id': '1', 'status': 'pass', 'severity': 'required', 'evidence': 'Text and image are clear'}]}}
    path = folder / ('a'*64 + '.json')
    path.write_text(json.dumps(record))
    path.with_suffix('.request.json').write_text(json.dumps({'kind': 'review', 'asset': 'pdf-face-01', 'status': 'completed',
        'input_hash': 'a'*64, 'report_hash': sha256(path.read_bytes())}))
    data = load(project)
    data['pages'][0]['image_box'] = [10, 10, 100, 80]
    save(project, data)
    with pytest.raises(ValueError) as blocked:
        layout.build(root, project)
    assert blocked.value.details['reason'] == 'accepted_page_changed'


def test_delivery_size_is_checked_before_replacing_previous_files(book):
    layout, root, project, _ = book
    layout.build(root, project)
    before = (project / 'book.pdf').read_bytes()
    old_preview = (project / 'previews/pages/page-1.png').read_bytes()
    data = load(project)
    data['pages'][0]['text_elements'] = [{'text': 'Changed', 'box': [10, 10, 100, 20]}]
    save(project, data)
    with pytest.raises(ValueError) as blocked:
        layout.build(root, project, max_file_bytes=64)
    assert blocked.value.details['reason'] == 'delivery_size_exceeded'
    assert (project / 'book.pdf').read_bytes() == before
    assert (project / 'previews/pages/page-1.png').read_bytes() == old_preview


def test_export_uses_jpeg_without_altering_source_art_or_vector_text(book):
    from pypdf import PdfReader
    layout, root, project, data = book
    art = (project / 'art.png').read_bytes()
    data['pages'][0]['text_elements'] = [{'text': 'Readable vector text', 'box': [5, 5, 110, 20]}]
    save(project, data)
    result = layout.build(root, project)
    assert (project / 'art.png').read_bytes() == art
    page = PdfReader(project / 'book.pdf').pages[0]
    assert 'Readable vector text' in page.extract_text()
    assert '/DCTDecode' in str(page['/Resources']['/XObject'].get_object()) or any(
        '/DCTDecode' in str(obj.get_object().get('/Filter')) for obj in page['/Resources']['/XObject'].get_object().values())
    assert result['delivery']['ready'] is True
    assert result['delivery']['files'][0]['size'] == (project / 'book.pdf').stat().st_size


def test_conditional_layout_contract_fails_before_render(book):
    layout, root, project, data = book
    data['pages'][0]['layout'] = 'context-to-detail'
    save(project, data)
    with pytest.raises(ValueError, match='context-to-detail'):
        layout.build(root, project)
    assert not (project / 'book.pdf').exists()


def test_delivery_preflight_exposes_exact_file_and_limit(book):
    layout, _, project, _ = book
    for name in dict.fromkeys(layout.DELIVERABLES.values()):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'file')
    with (project / 'book.pdf').open('wb') as stream:
        stream.truncate(20 * 1024 * 1024 + 85085)
    with pytest.raises(ValueError) as blocked:
        layout.delivery_status(project)
    assert blocked.value.details['file'] == 'book.pdf'
    assert blocked.value.details['actual_bytes'] == 20 * 1024 * 1024 + 85085
    assert blocked.value.details['max_file_bytes'] == 20 * 1024 * 1024
    assert blocked.value.details['retryable'] is False


def test_delivery_preflight_rejects_missing_and_empty_outputs_without_writes(book):
    layout, _, project, _ = book
    with pytest.raises(ValueError) as blocked:
        layout.delivery_status(project)
    assert blocked.value.details['reason'] == 'delivery_file_unavailable'
    assert not (project / 'book.pdf').exists()
    (project / 'book.pdf').write_bytes(b'')
    with pytest.raises(ValueError) as blocked:
        layout.delivery_status(project)
    assert blocked.value.details['actual_bytes'] == 0


def test_title_metadata_updates_without_page_render_or_qa_reset(book, monkeypatch):
    from pypdf import PdfReader
    layout, root, project, _ = book
    layout.build(root, project)
    data = load(project)
    data['qa'].update({key: True for key in data['qa']})
    data['title'] = 'New document title'
    save(project, data)
    previous = (project / 'previews/pages/page-1.png').read_bytes()
    monkeypatch.setattr(layout.subprocess, 'run', lambda *a, **k: pytest.fail('Metadata must not render'))
    result = layout.build(root, project)
    assert result['reused'] is True and result['changed_pages'] == []
    assert PdfReader(project / 'book.pdf').metadata.title == 'New document title'
    assert (project / 'previews/pages/page-1.png').read_bytes() == previous
    assert load(project)['qa'] == data['qa']


def test_only_changed_page_is_rendered_and_other_evidence_is_preserved(book, monkeypatch):
    layout, root, project, _ = book
    layout.build(root, project)
    previous = (project / 'previews/pages/page-2.png').read_bytes()
    data = load(project)
    data['pages'][0]['text_elements'] = [{'text': 'Changed page', 'box': [5, 5, 100, 20]}]
    save(project, data)
    original = layout.subprocess.run
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return original(args, **kwargs)
    monkeypatch.setattr(layout.subprocess, 'run', run)
    result = layout.build(root, project)
    assert result['changed_pages'] == [1] and result['rendered_pages'] == 1
    assert len(calls) == 1 and calls[0][calls[0].index('-f')+1] == '1'
    assert (project / 'previews/pages/page-2.png').read_bytes() == previous


def test_retired_pages_are_not_pending_but_reactivation_retains_their_budget(book):
    from bookbot.render_state import render_status
    layout, root, project, _ = book
    layout.build(root, project)
    saved = load(project)
    reduced = load(project)
    reduced['pages'] = reduced['pages'][:1]
    reduced['page_count'] = 1
    save(project, reduced)
    layout.build(root, project)
    status = render_status(project)
    assert status['pages']['2']['active'] is False
    assert 2 not in status['pending_pages']
    assert not (project / 'previews/pages/page-2.png').exists()
    save(project, saved)
    layout.build(root, project)
    assert render_status(project)['pages']['2']['versions'] == 2


def test_noisy_large_art_is_print_sized_instead_of_losslessly_embedded(book):
    from PIL import Image
    import random
    layout, root, project, data = book
    raw = random.Random(7).randbytes(2200 * 1600 * 3)
    Image.frombytes('RGB', (2200, 1600), raw).save(project / 'noise.png')
    data['pages'][0]['asset'] = 'noise.png'
    data['pages'][0]['image_fit'] = 'cover'
    save(project, data)
    result = layout.build(root, project)
    assert (project / 'book.pdf').stat().st_size < (project / 'noise.png').stat().st_size / 2
    assert result['delivery']['ready'] is True


def test_invalid_acceptance_proof_cannot_freeze_or_approve_a_page(book):
    from bookbot.common import sha256
    from bookbot.render_state import render_status
    layout, root, project, _ = book
    layout.build(root, project)
    folder = project / '.bookbot/reviews/pdf-face-01'
    folder.mkdir(parents=True)
    record = {'asset': 'pdf-face-01', 'input_hash': 'a'*64,
              'image_inputs': [{'role': 'target', 'sha256': sha256((project / 'previews/pages/page-1.png').read_bytes())}],
              'assessment': {'verdict': 'pass', 'checks': [
                  {'id': '1', 'severity': 'required', 'status': 'uncertain', 'evidence': 'Cannot verify'}]}}
    path = folder / ('a'*64 + '.json')
    path.write_text(json.dumps(record))
    path.with_suffix('.request.json').write_text(json.dumps({'kind': 'review', 'asset': 'pdf-face-01',
        'status': 'completed', 'input_hash': 'a'*64, 'report_hash': sha256(path.read_bytes())}))
    assert render_status(project)['pages']['1']['accepted'] is False
    assert 1 in render_status(project)['pending_pages']


def test_accepted_page_cannot_be_removed_to_bypass_freeze(book):
    from bookbot.common import sha256
    layout, root, project, data = book
    data['pages'][1] = {'page': 2, 'role': 'back-cover', 'asset': 'art.png', 'image_box': [0, 0, 120, 100]}
    save(project, data)
    layout.build(root, project)
    folder = project / '.bookbot/reviews/pdf-face-02'
    folder.mkdir(parents=True)
    record = {'asset': 'pdf-face-02', 'input_hash': 'b'*64,
              'image_inputs': [{'role': 'target', 'sha256': sha256((project / 'previews/pages/page-2.png').read_bytes())}],
              'assessment': {'verdict': 'pass', 'checks': [
                  {'id': '1', 'status': 'pass', 'severity': 'required', 'evidence': 'Visible required content'}]}}
    path = folder / ('b'*64 + '.json')
    path.write_text(json.dumps(record))
    path.with_suffix('.request.json').write_text(json.dumps({'kind': 'review', 'asset': 'pdf-face-02',
        'status': 'completed', 'input_hash': 'b'*64, 'report_hash': sha256(path.read_bytes())}))
    data = load(project)
    data['pages'] = data['pages'][:1]
    data['page_count'] = 1
    save(project, data)
    before = (project / 'book.pdf').read_bytes()
    with pytest.raises(ValueError) as blocked:
        layout.build(root, project)
    assert blocked.value.details['reason'] == 'accepted_page_changed'
    assert (project / 'book.pdf').read_bytes() == before


def test_text_position_only_invalidates_language_layout_not_story_or_character_review(book):
    layout, root, project, data = book
    data['pages'][0]['text_elements'] = [{'text': 'The same story', 'box': [5, 5, 100, 20]}]
    save(project, data)
    layout.build(root, project)
    data = load(project)
    data['qa'].update(story_reviewed=True, language_reviewed=True,
                      visual_continuity_reviewed=True, pdf_rendered_reviewed=True)
    data['pages'][0]['text_elements'][0]['box'] = [5, 10, 100, 20]
    save(project, data)
    result = layout.build(root, project)
    qa = load(project)['qa']
    assert qa['story_reviewed'] is True and qa['visual_continuity_reviewed'] is True
    assert qa['language_reviewed'] is False and qa['pdf_rendered_reviewed'] is False
    assert set(result['invalidated_checks']) == {'language_reviewed', 'pdf_rendered_reviewed', 'print_tested'}


def test_changing_words_keeps_character_continuity_but_invalidates_story(book):
    layout, root, project, data = book
    data['pages'][0]['text_elements'] = [{'text': 'First story', 'box': [5, 5, 100, 20]}]
    save(project, data)
    layout.build(root, project)
    data = load(project)
    data['qa'].update(story_reviewed=True, language_reviewed=True,
                      visual_continuity_reviewed=True, pdf_rendered_reviewed=True)
    data['pages'][0]['text_elements'][0]['text'] = 'Changed story'
    save(project, data)
    layout.build(root, project)
    qa = load(project)['qa']
    assert qa['story_reviewed'] is False and qa['language_reviewed'] is False
    assert qa['visual_continuity_reviewed'] is True


def test_numeric_serialization_changes_do_not_consume_visual_revisions(book, monkeypatch):
    layout, root, project, data = book
    data['pages'][0]['text_elements'] = [{'text': 'Unchanged', 'box': [5, 5, 100, 20], 'font_size': 18}]
    save(project, data)
    layout.build(root, project)
    data = load(project)
    data['format'].update(width_mm=120.0, height_mm=100.0)
    data['pages'][0]['image_box'] = [float(x) for x in data['pages'][0]['image_box']]
    data['pages'][0]['text_elements'][0]['box'] = [float(x) for x in data['pages'][0]['text_elements'][0]['box']]
    data['pages'][0]['text_elements'][0]['font_size'] = 18.0
    save(project, data)
    monkeypatch.setattr(layout.subprocess, 'run', lambda *a, **k: pytest.fail('No visual change'))
    result = layout.build(root, project)
    assert result['changed_pages'] == [] and result['reused'] is True

"""Single-page composition experiments do not mutate the production book."""
import importlib
import json
import subprocess
import sys

import pytest

from tests.test_picture_book_rendering import book as book, save
from tests.test_picture_book_convergence import cli_copy


def preview_module():
    return importlib.import_module('bookbot.preview')


def test_preview_handles_incomplete_book_without_changing_formal_outputs(book):
    from PIL import Image
    _, root, project, data = book
    data['pages'][0]['text_elements'] = [{'text':'A page with a clear story.', 'box':[10,10,90,25]}]
    data['pages'][1] = {'page':2, 'asset':'not-generated-yet.png', 'image_box':[0,0,120,100]}
    save(project, data)
    (project / 'book.pdf').write_bytes(b'Previous formal PDF')
    evidence = project / '.bookbot/render-state.json'
    evidence.parent.mkdir()
    evidence.write_text('{"preserve":"existing evidence"}')
    before = {name:(project/name).read_bytes() for name in ('book.json','book.pdf','.bookbot/render-state.json')}
    result = preview_module().preview(root, project, 1)
    assert result['page'] == 1 and result['text_regions'][0]['line_count'] > 0
    assert result['text_regions'][0]['used_height_mm'] < 25
    assert result['acceptance'] == 'not_evaluated'
    with Image.open(result['preview']) as full, Image.open(result['text_regions'][0]['preview']) as region:
        assert full.width > 600 and 0 < region.width < full.width
    assert {name:(project/name).read_bytes() for name in before} == before


def test_preview_candidate_uses_the_page_schema_without_publishing_it(book):
    _, root, project, data = book
    save(project,data)
    candidate = dict(data['pages'][0], text_elements=[
        {'text':'Look here.', 'box':[12,12,90,25], 'font_size':20, 'fill':'#ffffff'}])
    path = project / 'candidate.json'
    path.write_text(json.dumps(candidate))
    before = (project/'book.json').read_bytes()
    first = preview_module().preview(root,project,1,layout_file='candidate.json')
    assert first['text_regions'][0]['box'] == [12,12,90,25]
    candidate['text_elements'][0]['box'] = [12,60,90,25]
    path.write_text(json.dumps(candidate))
    second = preview_module().preview(root,project,1,layout_file='candidate.json')
    assert first['preview'] != second['preview']
    assert (project/'book.json').read_bytes() == before
    assert not (project/'book.pdf').exists()


def test_preview_rejects_wrong_page_and_overflow_without_changing_the_book(book):
    _, root, project, data = book
    candidate = dict(data['pages'][0], page=2)
    (project/'candidate.json').write_text(json.dumps(candidate))
    with pytest.raises(ValueError):
        preview_module().preview(root,project,1,layout_file='candidate.json')
    candidate.update(page=1,text_elements=[{'text':'A paragraph. '*20,'box':[1,1,10,10]}])
    (project/'candidate.json').write_text(json.dumps(candidate))
    with pytest.raises(ValueError,match='overflows'):
        preview_module().preview(root,project,1,layout_file='candidate.json')
    assert not (project/'book.pdf').exists()


def test_preview_cli_returns_actual_image_paths(book):
    _, root, project, data = book
    save(project,data)
    script = cli_copy(root)
    result = subprocess.run([sys.executable,str(script),'--project','example','preview','--page','1'],
                            capture_output=True,text=True,timeout=20)
    assert result.returncode == 0,result.stderr
    value=json.loads(result.stdout)
    assert value['page']==1 and value['text_regions']==[]
    from pathlib import Path
    assert Path(value['preview']).is_file()

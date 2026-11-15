"""Render a proposed page and text crops without publishing or accepting a book."""
from copy import deepcopy
import math
import shutil
import subprocess
from tempfile import TemporaryDirectory

from .common import confined, read_json
from .layout import _page_hashes, _write_pdf, validate_layout


def preview(root, project, number, *, layout_file=None):
    if type(number) is not int or number < 1:
        raise ValueError('Preview page must be a positive integer')
    if not shutil.which('pdftoppm'):
        raise ValueError('Install Poppler (pdftoppm) before previewing a page')
    source = read_json(project / 'book.json')
    if not isinstance(source, dict):
        raise ValueError('book.json must be an object')
    if layout_file:
        page = read_json(confined(project, layout_file))
    else:
        page = next((p for p in (source.get('pages') or []) if isinstance(p, dict) and p.get('page') == number), None)
    if not isinstance(page, dict) or page.get('page') != number:
        raise ValueError('Provide the requested page in book.json or a candidate page JSON')
    data = {'title': source.get('title') or 'Layout preview', 'format': deepcopy(source.get('format')),
            'page_count': 1, 'pages': [{**deepcopy(page), 'page': 1}]}
    width, height = validate_layout(data)
    fingerprint = _page_hashes(root, project, data)['1']
    output = confined(project, f'.bookbot/previews/page-{number:02d}-{fingerprint[:16]}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.layout-', dir=output.parent) as directory:
        from pathlib import Path
        from PIL import Image
        stage = Path(directory)
        regions = _write_pdf(root, project, data, stage / 'page.pdf')[0]
        subprocess.run(['pdftoppm', '-r', '144', '-singlefile', '-png', str(stage / 'page.pdf'),
                        str(stage / 'page')], check=True, capture_output=True, timeout=60)
        with Image.open(stage / 'page.png') as image:
            for index, region in enumerate(regions, 1):
                x, y, w, h = region['box']
                # A little surrounding artwork helps judge contrast and placement.
                crop = (max(0, math.floor((x - 2) / width * image.width)),
                        max(0, math.floor((y - 2) / height * image.height)),
                        min(image.width, math.ceil((x + w + 2) / width * image.width)),
                        min(image.height, math.ceil((y + h + 2) / height * image.height)))
                filename = f'text-{index:02d}.png'
                image.crop(crop).save(stage / filename)
                region['preview'] = str(output / filename)
        output.mkdir(exist_ok=True)
        for file in stage.iterdir():
            shutil.copy2(file, output / file.name)
    return {'page': number, 'input_hash': fingerprint, 'preview': str(output / 'page.png'),
            'text_regions': regions, 'acceptance': 'not_evaluated',
            'next': 'Inspect composition and readability in the full page; use text crops when needed. '
                    'Choose the layout, update book.json, then build and review the actual final pages.'}

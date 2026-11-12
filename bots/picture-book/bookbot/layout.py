"""Explicit millimetre layout; embedded Chinese text and complete PDF renders."""
import math
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .common import confined, read_json, write_json, atomic_bytes, sha256, book_config
from .production import Production, ProductionBlocked
from .render_state import load_state, plan_versions, completed_state, render_status

DELIVERABLES = {'reading_pdf': 'book.pdf', 'home_print_pdf': 'book.pdf',
                'full_preview': 'previews/overview.jpg', 'cover_back_preview': 'previews/covers.png',
                'printing_instructions': '打印说明.md'}

PAGE_FIELDS = {'page', 'role', 'title', 'text', 'blank', 'blank_reason', 'layout',
               'asset', 'image_box', 'image_fit', 'text_elements', 'context_asset', 'detail_asset',
               'arrow_count', 'notes'}
TEXT_FIELDS = {'text', 'box', 'font_size', 'align', 'fill'}


def validate_layout(data):
    """Reject unsupported rendering instructions before touching any output."""
    if not isinstance(data, dict):
        raise ValueError('book.json must be an object')
    pages = data.get('pages')
    if (not isinstance(pages, list) or not pages or type(data.get('page_count')) is not int
            or len(pages) != data['page_count'] or len(pages) > 128):
        raise ValueError('book.json pages must match page_count (1–128)')
    if not isinstance(data.get('title'), str) or not data['title'].strip():
        raise ValueError('title must be a nonempty string')
    fmt = data.get('format')
    if not isinstance(fmt, dict):
        raise ValueError('format must define width_mm and height_mm')
    width, height = (fmt.get(n) for n in ('width_mm', 'height_mm'))
    if any(type(n) not in (int, float) or not math.isfinite(n) or not 50 <= n <= 600 for n in (width, height)):
        raise ValueError('Page size must be 50–600 mm')
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            raise ValueError(f'Page {number} must be an object')
        unknown = page.keys() - PAGE_FIELDS
        if unknown:
            raise ValueError(f'Page {number}: unsupported fields {", ".join(sorted(unknown))}; '
                             'use asset/image_box and text_elements; see build --help')
        if type(page.get('page')) is not int or page['page'] != number:
            raise ValueError('Pages must have consecutive 1-based page numbers')
        if type(page.get('blank', False)) is not bool:
            raise ValueError(f'Page {number}: blank must be boolean')
        if page.get('blank') and any(page.get(k) for k in ('text', 'asset', 'image_box', 'image_fit', 'text_elements')):
            raise ValueError(f'Page {number}: blank pages cannot contain text or artwork')
        if page.get('image_fit', 'contain') not in ('cover', 'contain'):
            raise ValueError(f'Page {number}: image_fit must be cover or contain')
        if page.get('layout') == 'context-to-detail' and (page.get('arrow_count') != 1
                or not page.get('context_asset') or not page.get('detail_asset')):
            raise ValueError(f'Page {number}: context-to-detail requires arrow_count=1, context_asset and detail_asset')
        if page.get('text'):
            raise ValueError(f'Page {number}: move text into text_elements; page text is not rendered')
        if 'asset' in page:
            if not isinstance(page['asset'], str) or not page['asset'].strip():
                raise ValueError(f'Page {number}: asset must be a nonempty project-relative image path')
            _box(page.get('image_box'), width, height)
        elif 'image_box' in page:
            raise ValueError(f'Page {number}: image_box requires asset')
        elements = page.get('text_elements', [])
        if not isinstance(elements, list):
            raise ValueError(f'Page {number}: text_elements must be a list')
        for item in elements:
            if not isinstance(item, dict):
                raise ValueError(f'Page {number}: text_elements entries must be objects')
            unknown = item.keys() - TEXT_FIELDS
            if unknown:
                raise ValueError(f'Page {number}: unsupported text fields {", ".join(sorted(unknown))}; '
                                 'supported: text, box, font_size, align, fill')
            if not isinstance(item.get('text'), str) or not item['text'].strip():
                raise ValueError(f'Page {number}: text must be a nonempty string')
            _box(item.get('box'), width, height)
            size = item.get('font_size', 18)
            if type(size) not in (int, float) or not math.isfinite(size) or not 8 <= size <= 72:
                raise ValueError(f'Page {number}: font_size must be 8–72 points')
            if item.get('align', 'left') not in ('left', 'center', 'right'):
                raise ValueError(f'Page {number}: align must be left, center or right')
            if not isinstance(item.get('fill', '#1f1f29'), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item.get('fill', '#1f1f29')):
                raise ValueError(f'Page {number}: fill must be a #RRGGBB colour')
    return width, height


def font_path(root):
    configured = book_config(root).get('font')
    candidates = ([Path(root) / configured] if configured else []) + [
        Path('/System/Library/Fonts/Supplemental/Songti.ttc'),
        Path('/usr/share/fonts/truetype/arphic/uming.ttc'),
        Path('C:/Windows/Fonts/msyh.ttc'),
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise ValueError('Configure endpoints.yml picture_book.font with an embeddable Chinese TrueType .ttf/.ttc font')


def _box(value, width, height):
    if (not isinstance(value, list) or len(value) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in value)):
        raise ValueError('Each box must be [left, top, width, height] in millimetres')
    x, y, w, h = value
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > width + .01 or y + h > height + .01:
        raise ValueError('Layout box exceeds page bounds')
    return value


def _lines(text, font, size, width):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for character in paragraph:
            if stringWidth(line + character, font, size) > width:
                if not line:
                    raise ValueError('Text box is narrower than one character')
                lines.append(line)
                line = character
            else:
                line += character
        lines.append(line)
    return lines


def _page_hashes(root, project, data):
    font = sha256(font_path(root).read_bytes())
    geometry = {key: float(data['format'][key]) for key in ('width_mm', 'height_mm')}
    result = {}
    for page in data['pages']:
        value = {'blank': page.get('blank', False), 'geometry': geometry, 'renderer': 3}
        if not value['blank']:
            value['font'] = font
            if page.get('asset'):
                value.update(art=sha256(confined(project, page['asset']).read_bytes()),
                             image_box=[float(n) for n in page['image_box']], image_fit=page.get('image_fit', 'contain'))
            value['text'] = [{'text': item['text'], 'box': [float(n) for n in item['box']],
                             'font_size': float(item.get('font_size', 18)), 'align': item.get('align', 'left'),
                             'fill': item.get('fill', '#1f1f29').lower()}
                            for item in page.get('text_elements', [])]
        result[str(page['page'])] = sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())
    return result


def _review_hashes(project, data):
    story, artwork = [], []
    for page in data['pages']:
        art = None
        if page.get('asset'):
            fit = page.get('image_fit', 'contain')
            box = page['image_box']
            art = {'bytes': sha256(confined(project, page['asset']).read_bytes()), 'fit': fit,
                   'crop_ratio': box[2] / box[3] if fit == 'cover' else None}
        artwork.append(art)
        story.append({'art': art, 'text': [item['text'] for item in page.get('text_elements', [])]})
    return {key: sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())
            for key, value in [('story_reviewed', story), ('visual_continuity_reviewed', artwork)]}


def input_hash(root, project, data):
    """Only actual drawing inputs, independent of editorial/printing labels."""
    return sha256(json.dumps(_page_hashes(root, project, data), sort_keys=True).encode())


def _metadata_hash(data):
    return sha256(json.dumps({'title': data['title'], 'printing': data.get('printing'),
                             'pages': data['pages'], 'format': data['format']},
                            sort_keys=True, ensure_ascii=False).encode())


def _page_name(number, count):
    return f'previews/pages/page-{number:0{len(str(count))}d}.png'


def _output_paths(data):
    return set(DELIVERABLES.values()) | {_page_name(n, data['page_count']) for n in range(1, data['page_count'] + 1)}


def require_current_render(root, project):
    data = read_json(project / 'book.json')
    validate_layout(data)
    if (data.get('render_input_hash') != input_hash(root, project, data)
            or data.get('render_metadata_hash') != _metadata_hash(data)
            or any(data.get('deliverables', {}).get(role) != path for role, path in DELIVERABLES.items())
            or not (project / 'book.pdf').is_file()
            or data.get('render_output_hash') != sha256((project / 'book.pdf').read_bytes())):
        raise ValueError('Book source or PDF changed; rebuild and review before validation/publication')
    outputs = data.get('render_outputs', {})
    for name in _output_paths(data):
        file = confined(project, name)
        if not file.is_file() or outputs.get(name) != sha256(file.read_bytes()):
            raise ValueError('Book deliverables changed; rebuild and review before validation/publication')


def _delivery(paths, maximum):
    if type(maximum) is not int or maximum < 1:
        raise ValueError('max_file_bytes must be a positive integer')
    files = []
    for name, path in paths.items():
        row = {'path': name, 'size': None}
        try:
            if not path.is_file():
                row['problem'] = 'not_regular_file' if path.exists() else 'missing'
            else:
                row['size'] = path.stat().st_size
                if row['size'] == 0:
                    row['problem'] = 'empty'
                elif row['size'] > maximum:
                    row['problem'] = 'too_large'
        except OSError:
            row['problem'] = 'unavailable'
        files.append(row)
    invalid = [row for row in files if row.get('problem')]
    if invalid:
        first = invalid[0]
        oversized = first['problem'] == 'too_large'
        raise ProductionBlocked('delivery_size_exceeded' if oversized else 'delivery_file_unavailable', 'book',
            'Prepared deliverable exceeds the receiving tool file limit' if oversized else 'Prepared deliverable is missing, empty or unavailable',
            'Keep the prior package; fix the identified export before final review or sending',
            file=first['path'], actual_bytes=first['size'], max_file_bytes=maximum, files=invalid)
    return {'max_file_bytes': maximum, 'files': files, 'ready': True}


def delivery_status(project, max_file_bytes=20 * 1024 * 1024):
    """Read-only receiving-tool preflight shared by build and deliverables."""
    return _delivery({name: confined(project, name) for name in dict.fromkeys(DELIVERABLES.values())}, max_file_bytes)


def _print_instructions(data, width, height):
    pages = data['pages']
    lines = [data['title'], f'PDF {len(pages)}面；成品 {width}×{height}毫米。',
             '实际大小100%，每面1页；保留全部空白，不使用小册子或跳过空白页。']
    if (data.get('printing') or {}).get('profile') == 'separate-covers-title':
        lines += ['按正常顺序双面打印；第一张和最后一张为独立厚封纸，第二张为扉页纸，其余为内文。',
                  '横向左侧环装通常使用短边翻转，具体翻转方向必须先试印。']
    lines += ['', f'纸张与页面对应：{len(pages)}面，共{math.ceil(len(pages) / 2)}张纸。',
              '| 纸张 | 正面 PDF 面 | 反面 PDF 面 |', '| --- | --- | --- |']
    for index in range(0, len(pages), 2):
        back = str(index + 2) if index + 1 < len(pages) else '留白'
        lines.append(f'| {index // 2 + 1} | {index + 1} | {back} |')
    lines += ['', '本文件完成数字排版与渲染；内容/视觉审校另看审校记录，实物打印仍需试印。']
    return ('\n'.join(lines) + '\n').encode()


def _image_reader(path, width_mm, height_mm, fit):
    """A deterministic print-sized derivative; original artwork stays intact."""
    from PIL import Image, ImageOps
    from reportlab.lib.utils import ImageReader
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGBA')
        if fit == 'cover':
            ratio = width_mm / height_mm
            w, h = image.size
            crop = (max(1, round(h * ratio)), h) if w / h > ratio else (w, max(1, round(w / ratio)))
            image = ImageOps.fit(image, crop, method=Image.Resampling.LANCZOS)
        image.thumbnail((max(1, round(width_mm / 25.4 * 240)), max(1, round(height_mm / 25.4 * 240))),
                        Image.Resampling.LANCZOS)
        flattened = Image.new('RGB', image.size, 'white')
        flattened.paste(image, mask=image.getchannel('A'))
        stream = io.BytesIO()
        flattened.save(stream, format='JPEG', quality=95, subsampling=0, optimize=True)
    stream.seek(0)
    return ImageReader(stream)


def _write_pdf(root, project, data, output):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.units import mm
    from pypdf import PdfReader
    width, height = data['format']['width_mm'], data['format']['height_mm']
    font = TTFont('PictureBookChinese', str(font_path(root)))
    pdfmetrics.registerFont(font)
    canvas = Canvas(str(output), pagesize=(width * mm, height * mm), pageCompression=1)
    canvas.setTitle(data['title'])
    canvas.setAuthor('Cota Picture Book')
    for page in data['pages']:
        if not page.get('blank'):
            if page.get('asset'):
                x, y, w, h = page['image_box']
                fit = page.get('image_fit', 'contain')
                reader = _image_reader(confined(project, page['asset']), w, h, fit)
                canvas.drawImage(reader, x * mm, (height - y - h) * mm, w * mm, h * mm,
                                 preserveAspectRatio=fit == 'contain', anchor='c')
            for item in page.get('text_elements', []):
                x, y, w, h = item['box']
                size = item.get('font_size', 18)
                if any(ord(c) not in font.face.charToGlyph for c in item['text'] if not c.isspace()):
                    raise ValueError('Chinese font is missing required glyphs; choose another font')
                lines = _lines(item['text'], font.fontName, size, w * mm)
                leading = size * 1.4
                if len(lines) * leading > h * mm:
                    raise ValueError(f"Page {page['page']}: text overflows its box; revise the text or layout")
                canvas.setFont(font.fontName, size)
                colour = item.get('fill', '#1f1f29')
                canvas.setFillColorRGB(*(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)))
                align = item.get('align', 'left')
                draw = {'left': canvas.drawString, 'center': canvas.drawCentredString, 'right': canvas.drawRightString}[align]
                anchor = x + {'left': 0, 'center': w / 2, 'right': w}[align]
                for line_no, line in enumerate(lines):
                    draw(anchor * mm, (height - y) * mm - size - line_no * leading, line)
        canvas.showPage()
    canvas.save()
    if len(PdfReader(output).pages) != len(data['pages']):
        raise ValueError('PDF page count mismatch')


def _preview_images(stage, project, data, numbers):
    from PIL import Image, ImageOps
    count = data['page_count']
    prefix = stage / 'pages/page'
    prefix.parent.mkdir()
    all_numbers = list(range(1, count + 1))
    if numbers == all_numbers:
        subprocess.run(['pdftoppm', '-r', '90', '-png', str(stage / 'book.pdf'), str(prefix)],
                       check=True, capture_output=True, timeout=180)
    else:
        for number in numbers:
            subprocess.run(['pdftoppm', '-r', '90', '-f', str(number), '-l', str(number), '-png',
                            str(stage / 'book.pdf'), str(prefix)], check=True, capture_output=True, timeout=180)
    paths = []
    for number in all_numbers:
        name = Path(_page_name(number, count)).name
        target = stage / 'pages' / name
        if not target.exists():
            shutil.copy2(project / _page_name(number, count), target)
        paths.append(target)
    thumbnails = []
    for path in paths:
        with Image.open(path) as image:
            thumbnails.append(ImageOps.contain(image.convert('RGB'), (320, 250)).copy())
    overview = Image.new('RGB', (4 * 340, math.ceil(len(paths) / 4) * 270), '#eeeae2')
    for i, thumbnail in enumerate(thumbnails):
        overview.paste(thumbnail, ((i % 4) * 340 + 10, (i // 4) * 270 + 10))
    overview.save(stage / 'overview.jpg', quality=90)
    covers = Image.new('RGB', (680, 270), '#eeeae2')
    covers.paste(thumbnails[0], (10, 10))
    covers.paste(thumbnails[-1], (350, 10))
    covers.save(stage / 'covers.png')
    return paths


def build(root, project, *, max_file_bytes=20 * 1024 * 1024):
    if type(max_file_bytes) is not int or max_file_bytes < 1:
        raise ValueError('max_file_bytes must be a positive integer')
    if not shutil.which('pdftoppm'):
        raise ValueError('Install Poppler (pdftoppm) before building a book')
    with Production(project, 'render'):
        data = read_json(project / 'book.json')
        width, height = validate_layout(data)
        # Physical sheet count is deterministic, never a manual renderer input.
        data.setdefault('printing', {})['sheets'] = math.ceil(data['page_count'] / 2)
        hashes = _page_hashes(root, project, data)
        reviews = _review_hashes(project, data)
        fingerprint = sha256(json.dumps(hashes, sort_keys=True).encode())
        state = load_state(project, data)
        changed = plan_versions(project, state, hashes)
        result = {'pdf': 'book.pdf', 'pages': data['page_count'], 'rendered_pages': 0,
                  'preview': 'previews/overview.jpg', 'physical_proof': 'pending',
                  'manifest': 'book.json', 'input_hash': fingerprint, 'changed_pages': changed, 'reused': False}
        intact = False
        try:
            require_current_render(root, project)
            intact = True
        except ValueError:
            # Metadata may be stale while visual outputs are still intact.
            intact = (data.get('render_input_hash') == fingerprint
                      and all((project / name).is_file() and data.get('render_outputs', {}).get(name)
                              == sha256((project / name).read_bytes()) for name in _output_paths(data)))
        visual_reuse = not changed and intact
        metadata_changed = data.get('render_metadata_hash') != _metadata_hash(data)
        with tempfile.TemporaryDirectory(prefix='.layout-', dir=project) as temporary:
            stage = Path(temporary)
            if visual_reuse:
                result['reused'] = True
                if data.get('render_document_title') != data['title']:
                    from pypdf import PdfReader, PdfWriter
                    writer = PdfWriter()
                    writer.clone_document_from_reader(PdfReader(project / 'book.pdf'))
                    writer.add_metadata({'/Title': data['title'], '/Author': 'Cota Picture Book'})
                    writer.write(stage / 'book.pdf')
                else:
                    shutil.copy2(project / 'book.pdf', stage / 'book.pdf')
                for name in _output_paths(data) - {'book.pdf', '打印说明.md'}:
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(project / name, target)
            else:
                _write_pdf(root, project, data, stage / 'book.pdf')
                numbers = set(changed)
                for number in range(1, data['page_count'] + 1):
                    name = _page_name(number, data['page_count'])
                    file = project / name
                    if (not file.is_file() or state['pages'].get(str(number), {}).get('preview_hash')
                            != sha256(file.read_bytes())):
                        numbers.add(number)
                if not numbers:
                    numbers = set(range(1, data['page_count'] + 1))
                previews = _preview_images(stage, project, data, sorted(numbers))
                result['rendered_pages'] = len(numbers)
                for path in previews:
                    destination = stage / 'previews/pages' / path.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
                shutil.copy2(stage / 'overview.jpg', stage / 'previews/overview.jpg')
                shutil.copy2(stage / 'covers.png', stage / 'previews/covers.png')
            instructions = _print_instructions(data, width, height)
            (stage / '打印说明.md').write_bytes(instructions)
            previous_instructions = project / '打印说明.md'
            # A title-only edit is metadata; changed physical assembly guidance
            # requires a new print proof even when all page pixels are reused.
            print_changed = (previous_instructions.is_file()
                             and previous_instructions.read_bytes().partition(b'\n')[2]
                             != instructions.partition(b'\n')[2])
            delivery_names = list(dict.fromkeys(DELIVERABLES.values()))
            result['delivery'] = _delivery({name: stage / name for name in delivery_names}, max_file_bytes)
            preview_hashes = {str(n): sha256((stage / _page_name(n, data['page_count'])).read_bytes())
                              for n in range(1, data['page_count'] + 1)}
            new_state = completed_state(state, hashes, preview_hashes,
                                        {str(p['page']) for p in data['pages'] if p.get('blank')})
            # All expensive work/size checks completed before replacing evidence.
            if not visual_reuse or metadata_changed:
                for name in _output_paths(data):
                    source = stage / name
                    target = project / name
                    if not target.exists() or target.read_bytes() != source.read_bytes():
                        atomic_bytes(target, source.read_bytes())
            removed_content = any(not state['pages'][n]['blank'] for n in set(state.get('active_pages', state['pages'])) - hashes.keys())
            invalidated = []
            if changed or removed_content:
                invalidated = ['language_reviewed', 'pdf_rendered_reviewed', 'print_tested']
                invalidated += [key for key, value in reviews.items()
                                if data.get('review_fingerprints', {}).get(key) != value]
            elif not visual_reuse:
                invalidated = ['pdf_rendered_reviewed', 'print_tested']
            if print_changed and 'print_tested' not in invalidated:
                invalidated.append('print_tested')
            data.setdefault('qa', {}).update({key: False for key in invalidated})
            result['invalidated_checks'] = invalidated
            data['review_fingerprints'] = reviews
            data['print_status'] = 'pending-physical-proof' if not data.get('qa', {}).get('print_tested') else data.get('print_status')
            data['render_input_hash'] = fingerprint
            data['render_page_hashes'] = hashes
            data['render_metadata_hash'] = _metadata_hash(data)
            data['render_document_title'] = data['title']
            data['render_output_hash'] = sha256((project / 'book.pdf').read_bytes())
            data.setdefault('deliverables', {}).update(DELIVERABLES)
            data['sheet_map'] = [{'sheet': i // 2 + 1, 'front': i + 1,
                                 'back': i + 2 if i + 1 < data['page_count'] else None}
                                for i in range(0, data['page_count'], 2)]
            data['render_outputs'] = {name: sha256((project / name).read_bytes()) for name in _output_paths(data)}
            expected_previews = {Path(_page_name(n, data['page_count'])).name for n in range(1, data['page_count'] + 1)}
            for old in (project / 'previews/pages').glob('page-*.png'):
                if old.name not in expected_previews:
                    old.unlink()
            write_json(project / '.bookbot/render-state.json', new_state)
            write_json(project / 'book.json', data)
        result['pending_pages'] = render_status(project)['pending_pages']
        return result

"""Explicit millimetre layout; embedded Chinese text and complete PDF renders."""
import math
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .common import confined, read_json, write_json, atomic_bytes, sha256, book_config

DELIVERABLES = {'reading_pdf': 'book.pdf', 'home_print_pdf': 'book.pdf',
                'full_preview': 'previews/overview.jpg', 'cover_back_preview': 'previews/covers.png',
                'printing_instructions': '打印说明.md'}


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


def input_hash(root, project, data):
    sources = {p['asset']: sha256(confined(project, p['asset']).read_bytes())
               for p in data['pages'] if p.get('asset')}
    return sha256(json.dumps({'pages': data['pages'], 'format': data['format'], 'assets': sources,
                             'title': data['title'], 'printing': data.get('printing'),
                             'font': sha256(font_path(root).read_bytes()), 'renderer': 1},
                            sort_keys=True, ensure_ascii=False).encode())


def require_current_render(root, project):
    data = read_json(project / 'book.json')
    if (data.get('render_input_hash') != input_hash(root, project, data)
            or any(data.get('deliverables', {}).get(role) != path for role, path in DELIVERABLES.items())
            or not (project / 'book.pdf').is_file()
            or data.get('render_output_hash') != sha256((project / 'book.pdf').read_bytes())):
        raise ValueError('Book source or PDF changed; rebuild and review before validation/publication')
    outputs = data.get('render_outputs', {})
    for path in set(DELIVERABLES.values()):
        file = confined(project, path)
        if not file.is_file() or outputs.get(path) != sha256(file.read_bytes()):
            raise ValueError('Book deliverables changed; rebuild and review before validation/publication')


def build(root, project):
    from PIL import Image, ImageOps
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.units import mm
    from pypdf import PdfReader

    if not shutil.which('pdftoppm'):
        raise ValueError('Install Poppler (pdftoppm) before building a book')
    data = read_json(project / 'book.json')
    pages = data.get('pages', [])
    if not pages or len(pages) != data.get('page_count') or len(pages) > 128:
        raise ValueError('book.json pages must match page_count (1–128)')
    if [p.get('page') for p in pages] != list(range(1, len(pages) + 1)):
        raise ValueError('Pages must have consecutive 1-based page numbers')
    width, height = (data['format'][n] for n in ('width_mm', 'height_mm'))
    if any(type(n) not in (int, float) or not math.isfinite(n) or not 50 <= n <= 600 for n in (width, height)):
        raise ValueError('Page size must be 50–600 mm')
    font_file = font_path(root)
    font = TTFont('PictureBookChinese', str(font_file))
    pdfmetrics.registerFont(font)
    fingerprint = input_hash(root, project, data)
    # Fail before writing anything if a font silently lacks a requested glyph.
    for page in pages:
        if page.get('blank'):
            if any(page.get(k) for k in ('text', 'asset', 'text_elements', 'lines')):
                raise ValueError('Blank pages cannot contain text or artwork')
            continue
        if page.get('text') and not page.get('text_elements'):
            raise ValueError('Move page text into explicit text_elements boxes; no implicit layout')
        for item in page.get('text_elements', []):
            if any(ord(c) not in font.face.charToGlyph for c in item['text'] if not c.isspace()):
                raise ValueError('Chinese font is missing required glyphs; choose another font')
    with tempfile.TemporaryDirectory(prefix='.layout-', dir=project) as temporary:
        stage = Path(temporary)
        output = stage / 'book.pdf'
        canvas = Canvas(str(output), pagesize=(width * mm, height * mm))
        canvas.setTitle(data['title'])
        canvas.setAuthor('Cota Picture Book')
        for page in pages:
            if not page.get('blank'):
                if page.get('asset'):
                    x, y, w, h = _box(page.get('image_box'), width, height)
                    path = confined(project, page['asset'])
                    with Image.open(path) as image:
                        image.load()
                        canvas.drawImage(ImageReader(image), x * mm, (height - y - h) * mm,
                                         w * mm, h * mm, preserveAspectRatio=True, anchor='c', mask='auto')
                for item in page.get('text_elements', []):
                    x, y, w, h = _box(item.get('box'), width, height)
                    size = item.get('font_size', 18)
                    if type(size) not in (int, float) or not math.isfinite(size) or not 8 <= size <= 72:
                        raise ValueError('font_size must be 8–72 points')
                    lines = _lines(item['text'], font.fontName, size, w * mm)
                    leading = size * 1.4
                    if len(lines) * leading > h * mm:
                        raise ValueError(f"Page {page['page']}: text overflows its box; revise the text or layout")
                    canvas.setFont(font.fontName, size)
                    canvas.setFillColorRGB(0.12, 0.12, 0.16)
                    for line_no, line in enumerate(lines):
                        canvas.drawString(x * mm, (height - y) * mm - size - line_no * leading, line)
            canvas.showPage()
        canvas.save()
        if len(PdfReader(output).pages) != len(pages):
            raise ValueError('PDF page count mismatch')
        rendered = stage / 'pages'
        rendered.mkdir()
        # No shell interpolation; all pages, including structural blanks.
        subprocess.run(['pdftoppm', '-r', '90', '-png', str(output), str(rendered / 'page')],
                       check=True, capture_output=True, timeout=180)
        paths = sorted(rendered.glob('page-*.png'), key=lambda p: int(p.stem.split('-')[-1]))
        if len(paths) != len(pages):
            raise ValueError('Not every PDF page was rendered')
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
        # Only commit completed outputs, after layout and rendering succeed.
        atomic_bytes(project / 'book.pdf', output.read_bytes())
        for path in paths:
            atomic_bytes(project / 'previews/pages' / path.name, path.read_bytes())
        expected = {p.name for p in paths}
        for old in (project / 'previews/pages').glob('page-*.png'):
            if old.name not in expected:
                old.unlink()
        atomic_bytes(project / 'previews/overview.jpg', (stage / 'overview.jpg').read_bytes())
        atomic_bytes(project / 'previews/covers.png', (stage / 'covers.png').read_bytes())
    if data.get('render_input_hash') != fingerprint:
        data.setdefault('qa', {}).update(story_reviewed=False, language_reviewed=False,
            visual_continuity_reviewed=False, pdf_rendered_reviewed=False, print_tested=False)
        data['print_status'] = 'pending-physical-proof'
    data['render_input_hash'] = fingerprint
    data['render_output_hash'] = sha256((project / 'book.pdf').read_bytes())
    data.setdefault('deliverables', {}).update(DELIVERABLES)
    data['sheet_map'] = [{'sheet': i // 2 + 1, 'front': i + 1, 'back': i + 2}
                         for i in range(0, len(pages) - 1, 2)]
    instructions = (f"{data['title']}\nPDF {len(pages)}面；成品 {width}×{height}毫米。\n"
                    '实际大小100%，每面1页；保留全部空白，不使用小册子或跳过空白页。\n')
    if (data.get('printing') or {}).get('profile') == 'separate-covers-title':
        instructions += ('按正常顺序双面打印；第一张和最后一张为独立厚封纸，第二张为扉页纸，其余为内文。\n'
                         '横向左侧环装通常使用短边翻转，具体翻转方向必须先试印。\n')
    instructions += '本文件完成数字排版与渲染；内容/视觉审校另看审校记录，实物打印仍需试印。\n'
    atomic_bytes(project / '打印说明.md', instructions.encode())
    data['render_outputs'] = {path: sha256((project / path).read_bytes()) for path in set(DELIVERABLES.values())}
    write_json(project / 'book.json', data)
    return {'pdf': 'book.pdf', 'pages': len(pages), 'rendered_pages': len(paths),
            'preview': 'previews/overview.jpg', 'physical_proof': 'pending'}

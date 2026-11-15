"""Readable text over artwork, rendered locally without model services."""
import pytest

from tests.test_picture_book_rendering import book as book, load, save


def text_page(book):
    from PIL import Image
    layout, root, project, data = book
    Image.new('RGB', (800, 600), '#151515').save(project / 'art.png')
    data['pages'][0]['image_fit'] = 'cover'
    data['pages'][0]['text_elements'] = [{'text': '飞机为什么会飞？', 'box': [10, 10, 100, 30], 'font_size': 18}]
    return layout, root, project, data


def sample(image, x, y):
    return image.convert('RGB').getpixel((round(x / 120 * image.width), round(y / 100 * image.height)))


def test_default_text_is_transparent_and_remains_vector_text(book):
    from PIL import Image
    from pypdf import PdfReader
    layout, root, project, data = text_page(book)
    save(project, data)
    layout.build(root, project)
    with Image.open(project / 'previews/pages/page-1.png') as image:
        assert max(sample(image, 105, 15)) < 40
        assert max(sample(image, 30, 38)) < 40  # Do not blanket unused artwork.
        assert max(sample(image, 5, 5)) < 40
    assert '飞机为什么会飞' in PdfReader(project / 'book.pdf').pages[0].extract_text()
    explicit = load(project)
    explicit['pages'][0]['text_elements'][0].update(background=None, padding=0)
    save(project, explicit)
    assert layout.build(root, project)['reused']


def test_optional_background_is_only_drawn_when_explicitly_requested(book):
    from PIL import Image
    layout, root, project, data = text_page(book)
    save(project, data)
    layout.build(root, project)
    updated = load(project)
    updated['pages'][0]['text_elements'][0].update(background='#fffaf0', padding=1)
    save(project, updated)
    assert layout.build(root, project)['changed_pages'] == [1]
    with Image.open(project / 'previews/pages/page-1.png') as image:
        assert min(sample(image, 105, 15)) > 220


def test_renderer_does_not_impose_a_hard_aesthetic_contrast_threshold(book):
    layout, root, project, data = text_page(book)
    data['pages'][0]['text_elements'][0].update(background='#dddddd', fill='#cccccc')
    save(project, data)
    assert layout.build(root, project)['rendered_pages'] == 2
    assert not load(project)['qa']['pdf_rendered_reviewed']


@pytest.mark.parametrize('style', [
    {'background':'bad'},
    {'padding':-1}, {'padding':100}, {'padding':True},
])
def test_invalid_text_protection_fails_before_replacing_output(book, style):
    layout, root, project, data = text_page(book)
    save(project, data)
    layout.build(root, project)
    before = (project / 'book.pdf').read_bytes()
    updated = load(project)
    updated['pages'][0]['text_elements'][0].update(style)
    save(project, updated)
    with pytest.raises(ValueError):
        layout.build(root, project)
    assert (project / 'book.pdf').read_bytes() == before


def test_padding_counts_against_available_text_height(book):
    layout, root, project, data = text_page(book)
    data['pages'][0]['text_elements'][0].update(text='飞机', box=[10, 10, 50, 10], padding=3)
    save(project, data)
    with pytest.raises(ValueError, match='overflows'):
        layout.build(root, project)

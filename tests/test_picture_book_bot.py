"""Picture-book example: real files/PDF/HTTP, controlled paid-model boundaries."""
import base64
import importlib
import io
import json
from pathlib import Path

import httpx
import pytest
import yaml

BOT = Path(__file__).resolve().parents[1] / 'bots' / 'picture-book'


@pytest.fixture
def book_modules(monkeypatch):
    assert (BOT / 'bookbot' / 'models.py').is_file(), 'Portable picture-book implementation is missing'
    monkeypatch.syspath_prepend(str(BOT))
    return {name: importlib.import_module('bookbot.' + name) for name in ('common', 'models', 'layout')}


@pytest.fixture
def book_root(tmp_path):
    root = tmp_path / 'bot'
    root.mkdir()
    (root / 'endpoints.yml').write_text(yaml.safe_dump({'picture_book': {
        'image': {'key': 'PRIVATE_IMAGE_KEY', 'apibase': 'https://models.example/v1', 'model': 'image-model'},
        'vision': {'key': 'PRIVATE_VISION_KEY', 'apibase': 'https://models.example/v1', 'model': 'vision-model'},
    }}))
    project = root / 'workspace/books/example'
    project.mkdir(parents=True)
    return root, project


def image_bytes():
    Image = pytest.importorskip('PIL.Image')
    output = io.BytesIO()
    Image.new('RGB', (160, 100), '#aaccee').save(output, format='PNG')
    return output.getvalue()


def test_picture_book_is_portable_and_has_policy_eval():
    from cota.config import validate_bot_config
    from cota.policy.catalog import PolicyCatalog
    from cota.evaluation.schema import load_cases
    from cota.templates import template_files
    assert (BOT / 'agent.yml').is_file(), 'Picture-book Bot is missing'
    config = yaml.safe_load((BOT / 'agent.yml').read_text())
    validate_bot_config(config)
    assert config['deploy'] == 'personal'
    assert 'send_files' in config['tools']['allow']
    assert not (BOT / 'serve.py').exists()
    assert config['dialogue']['run_timeout_seconds'] >= 1800
    skill = BOT / 'skills/creating-childrens-picture-books'
    assert (skill / 'references/runtime-setup.md').is_file()
    assert (skill / 'references/themes/emotions.md').is_file()
    assert (skill / 'scripts/validate_book_package.py').is_file()
    paths = set(template_files(BOT))
    assert skill / 'assets/project-template/book.json' in paths
    assert BOT / 'bookbot/models.py' in paths
    PolicyCatalog.from_document(yaml.safe_load((BOT / 'policy/data.yml').read_text()))
    assert len(load_cases(BOT / 'policy/eval')) >= 8


def test_image_generate_edit_reuse_and_vision_receive_real_bytes(book_modules, book_root):
    models = book_modules['models']
    root, project = book_root
    prompt = project / 'prompt.txt'
    prompt.write_text('原创小兔；画面不出现文字。')
    reference = project / 'character.png'
    reference.write_bytes(image_bytes())
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/chat/completions'):
            body = json.loads(request.content)
            assert body['model'] == 'vision-model'
            assert 'data:image/png;base64,' in str(body['messages'])
            return httpx.Response(200, json={'choices': [{'message': {'content': '图中有一只小兔。'}}]})
        if request.url.path.endswith('/images/edits'):
            assert b'filename="character.png"' in request.content
            assert reference.read_bytes() in request.content
        else:
            assert json.loads(request.content)['model'] == 'image-model'
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = models.generate(root, project, prompt, 'first.png', client=client, asset='test-asset')
        again = models.generate(root, project, prompt, 'first.png', client=client, asset='test-asset')
        assert again['reused'] is True and len(requests) == 1
        assert first['sha256'] == again['sha256']
        models.generate(root, project, prompt, 'second.png', references=[reference], client=client, asset='test-asset')
        report = models.review(root, project, prompt, [reference], 'review.json', client=client, asset='test-asset')
        assert report['content'] == '图中有一只小兔。'
        prompt.write_text('改成小猫')
        with pytest.raises(ValueError, match='already exists'):
            models.generate(root, project, prompt, 'first.png', client=client, asset='test-asset')
    assert len(requests) == 3
    for record in project.rglob('*.json'):
        assert 'PRIVATE_' not in record.read_text()


@pytest.mark.parametrize('response', [httpx.Response(429, json={'error': 'PRIVATE_IMAGE_KEY'}),
                                      httpx.Response(200, json={'data': [{'url': 'https://untrusted/image.png'}]})])
def test_model_error_is_safe_and_never_publishes_placeholder(book_modules, book_root, response):
    pytest.importorskip('PIL')
    root, project = book_root
    prompt = project / 'prompt.txt'
    prompt.write_text('小兔')
    requests = []
    def handler(request):
        requests.append(request)
        return response
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError) as error:
            book_modules['models'].generate(root, project, prompt, 'failed.png', client=client, asset='test-asset')
    assert 'PRIVATE_' not in str(error.value)
    assert len(requests) == 1 and not (project / 'failed.png').exists()


def test_projects_cannot_escape_and_configs_are_optional_until_used(book_modules, book_root):
    root, project = book_root
    common = book_modules['common']
    assert common.project_path(root, 'example') == project
    for value in ('../../endpoints.yml', str(root), ''):
        with pytest.raises(ValueError):
            common.project_path(root, value)
    (root / 'endpoints.yml').write_text('{}')
    with pytest.raises(ValueError, match='picture_book.image'):
        common.model_config(root, 'image')


def qwen_config(root, **settings):
    endpoints = yaml.safe_load((root / 'endpoints.yml').read_text())
    endpoints['picture_book']['image'].update(api='qwen', model='qwen-image-3.0',
        download_hosts=['images.example'], **settings)
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))


def test_qwen_generation_reference_edit_and_url_download(book_modules, book_root):
    root, project = book_root
    qwen_config(root, size='1536x1024')
    (project / 'prompt.txt').write_text('同一只小兔换一个动作，无文字。')
    data = image_bytes()
    (project / 'reference.png').write_bytes(data)
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == 'GET':
            assert request.url.host == 'images.example'
            assert 'authorization' not in request.headers
            return httpx.Response(200, content=data, headers={'Content-Type':'image/png'})
        assert request.url.path == '/v1/images/generations'
        assert request.headers['Authorization'] == 'Bearer PRIVATE_IMAGE_KEY'
        body = json.loads(request.content)
        assert body['model'] == 'qwen-image-3.0' and body['n'] == 1
        assert body['size'] == '1536x1024'
        if len(calls) > 2:
            assert body['image'] == 'data:image/png;base64,' + base64.b64encode(data).decode()
        else:
            assert 'image' not in body
        return httpx.Response(200, json={'data':[{'url':'https://images.example/book.png?sig=PRIVATE_SIGNED_URL'}]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        first = book_modules['models'].generate(root, project, 'prompt.txt', 'first.png', client=client, asset='test-asset')
        assert book_modules['models'].generate(root, project, 'prompt.txt', 'first.png', client=client, asset='test-asset')['reused']
        book_modules['models'].generate(root, project, 'prompt.txt', 'edited.png', references=['reference.png'], client=client, asset='test-asset')
    assert len(calls) == 4 and first['status'] == 'completed'
    assert (project / 'edited.png').read_bytes().startswith(b'\x89PNG')
    assert all('PRIVATE_' not in p.read_text() for p in project.glob('*.json'))


@pytest.mark.parametrize('url', ['http://images.example/a.png', 'https://evil.example/a.png',
                                 'https://images.example.evil/a.png', 'https://user:pass@images.example/a.png',
                                 'https://127.0.0.1/a.png'])
def test_qwen_rejects_unapproved_image_urls_without_get(book_modules, book_root, url):
    pytest.importorskip('PIL')
    root, project = book_root
    qwen_config(root)
    (project / 'prompt.txt').write_text('小兔')
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'data':[{'url':url}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError) as error:
            book_modules['models'].generate(root, project, 'prompt.txt', 'bad.png', client=client, asset='test-asset')
    assert len(calls) == 1 and 'pass' not in str(error.value)
    assert not (project / 'bad.png').exists()


@pytest.mark.parametrize('failure', ['redirect', 'status', 'size', 'transport', 'invalid'])
def test_qwen_download_failure_does_not_leak_url_or_retry(book_modules, book_root, failure):
    pytest.importorskip('PIL')
    root, project = book_root
    qwen_config(root)
    (project / 'prompt.txt').write_text('小兔')
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'data':[{'url':'https://images.example/book.png?sig=PRIVATE_SIGNED_URL'}]})
        if failure == 'redirect':
            return httpx.Response(302, headers={'Location':'https://evil.example/'})
        if failure == 'status':
            return httpx.Response(403, content=b'PRIVATE_SIGNED_URL')
        if failure == 'size':
            return httpx.Response(200, headers={'Content-Length':str(33 * 1024 * 1024)}, content=b'oversize')
        if failure == 'transport':
            raise httpx.ReadTimeout('PRIVATE_SIGNED_URL', request=request)
        return httpx.Response(200, content=b'invalid image')
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(ValueError) as error:
            book_modules['models'].generate(root, project, 'prompt.txt', 'bad.png', client=client, asset='test-asset')
    assert len(calls) == 2 and 'PRIVATE_' not in str(error.value)
    assert not (project / 'bad.png').exists()
    assert json.loads((project / 'bad.request.json').read_text())['status'] == 'started'


def test_qwen_reference_limits_are_checked_before_requests(book_modules, book_root):
    root, project = book_root
    qwen_config(root)
    (project / 'prompt.txt').write_text('小兔')
    (project / 'reference.png').write_bytes(image_bytes())
    def unexpected(request):
        raise AssertionError('Invalid references must not invoke the provider')
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError, match='three|3'):
            book_modules['models'].generate(root, project, 'prompt.txt', 'bad.png',
                references=['reference.png'] * 4, client=client, asset='test-asset')
    assert not (project / 'bad.request.json').exists()


def test_unknown_image_api_fails_configuration_check(book_modules, book_root):
    root, _ = book_root
    qwen_config(root)
    data = yaml.safe_load((root / 'endpoints.yml').read_text())
    data['picture_book']['image']['api'] = 'unsupported'
    (root / 'endpoints.yml').write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='api'):
        book_modules['common'].model_config(root, 'image')


def test_qwen_download_stream_limit_without_content_length(book_modules, book_root, monkeypatch):
    pytest.importorskip('PIL')
    root, project = book_root
    qwen_config(root)
    (project / 'prompt.txt').write_text('小兔')
    monkeypatch.setattr(book_modules['models'], 'MAX_IMAGE_BYTES', 8)
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b'12345'
            yield b'67890'
    def handle(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'data':[{'url':'https://images.example/output.png'}]})
        return httpx.Response(200, stream=Chunks())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match='exceeds'):
            book_modules['models'].generate(root, project, 'prompt.txt', 'bad.png', client=client, asset='test-asset')
    assert not (project / 'bad.png').exists()


@pytest.mark.parametrize('hosts', [[], ['*'], ['localhost'], ['127.0.0.1'], ['*.com'], ['https://images.example'], 'images.example'])
def test_qwen_download_allowlist_is_validated(book_modules, book_root, hosts):
    root, _ = book_root
    qwen_config(root)
    data = yaml.safe_load((root / 'endpoints.yml').read_text())
    data['picture_book']['image']['download_hosts'] = hosts
    (root / 'endpoints.yml').write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='download_hosts'):
        book_modules['common'].model_config(root, 'image')


def make_book(project):
    roles = ['cover', 'inside-cover', 'title', 'blank', 'story', 'ending', 'inside-back-cover', 'back-cover']
    (project / 'art.png').write_bytes(image_bytes())
    data = {
        'title': '小兔的云朵', 'audience_age': '3—5岁', 'book_type': 'fantasy-adventure',
        'language': 'zh-CN', 'binding': 'ring', 'page_count': 8,
        'format': {'paper': 'A5', 'width_mm': 210, 'height_mm': 148, 'safe_margin_mm': 10},
        'printing': {'profile': 'separate-covers-title', 'title_single_sided': True,
                     'delivery_mode': 'single-pdf', 'sheets': 4, 'jobs': [], 'home': True},
        'pages': [{'page': i + 1, 'role': role, 'blank': role in ('blank', 'inside-cover', 'inside-back-cover'),
                   **({} if role in ('blank', 'inside-cover', 'inside-back-cover') else {
                       'asset': 'art.png', 'image_box': [10, 10, 190, 90],
                       'text_elements': [{'text': '小兔抬头，云朵轻轻飘过。', 'box': [10, 110, 190, 25], 'font_size': 16}]})}
                  for i, role in enumerate(roles)],
        'qa': {'story_reviewed': False, 'language_reviewed': False, 'visual_continuity_reviewed': False,
               'pdf_rendered_reviewed': False, 'print_tested': False},
        'print_status': 'pending-physical-proof',
    }
    (project / 'book.json').write_text(json.dumps(data, ensure_ascii=False))
    return data


def test_render_all_pages_preserves_blanks_chinese_and_review_flags(book_modules, book_root):
    pypdf = pytest.importorskip('pypdf')
    pytest.importorskip('reportlab')
    root, project = book_root
    data = make_book(project)
    try:
        book_modules['layout'].font_path(root)
    except ValueError:
        pytest.skip('Optional picture-book renderer needs a locally installed Chinese TrueType font')
    result = book_modules['layout'].build(root, project)
    reader = pypdf.PdfReader(project / result['pdf'])
    assert len(reader.pages) == 8
    assert '小兔' in reader.pages[0].extract_text()
    assert all(not reader.pages[i].extract_text().strip() and not list(reader.pages[i].images) for i in (1, 3, 6))
    assert len(list((project / 'previews/pages').glob('*.png'))) == 8
    manifest = json.loads((project / 'book.json').read_text())
    assert manifest['qa'] == data['qa']
    assert manifest['deliverables']['full_preview']
    assert len(manifest['sheet_map']) == 4
    assert abs(float(reader.pages[0].mediabox.width) * 25.4 / 72 - 210) < .1
    data['pages'][0]['text_elements'][0]['box'] = [10, 140, 190, 25]
    (project / 'book.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='box'):
        book_modules['layout'].build(root, project)


def test_init_copies_skill_scripts_and_no_author_environment(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cota import __main__ as cli
    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    copy = tmp_path / 'cota_projects/picture-book'
    assert (copy / 'bookbot/layout.py').read_bytes() == (BOT / 'bookbot/layout.py').read_bytes()
    assert not (copy / 'serve.py').exists()
    assert not (copy / 'workspace').exists()
    assert not (copy / '.cota').exists()
    import subprocess
    import sys
    checked = subprocess.run([sys.executable, str(copy / 'scripts/book.py'), 'doctor'],
                             cwd=tmp_path, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)['models']['image']['configured'] is False
    initialized = subprocess.run([sys.executable, str(copy / 'scripts/book.py'), 'init', 'new-book'],
                                 cwd=tmp_path, capture_output=True, text=True)
    assert initialized.returncode == 0, initialized.stderr
    assert (copy / 'workspace/books/new-book/book.json').is_file()


@pytest.mark.asyncio
async def test_real_pi_long_tool_chain_and_sqlite_resume(book_modules, tmp_path):
    import shutil
    import shlex
    import sys
    from cota.agent import Agent
    from cota.templates import TEMPLATE_IGNORE
    from cota.message.message import Message
    from tests.test_pi_runtime import call
    from tests.integration.test_example_bots import ModelHTTP
    from openai import AsyncOpenAI

    root = tmp_path / 'picture book'
    shutil.copytree(BOT, root, ignore=TEMPLATE_IGNORE)
    endpoints = yaml.safe_load((root / 'endpoints.yml').read_text())
    endpoints['llms']['default'].update(key='TEST_ONLY', apibase='https://model.example/v1', model='test-model')
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    script = ' '.join([shlex.quote(sys.executable), shlex.quote(str(root / 'scripts/book.py'))])
    skill = root / 'skills/creating-childrens-picture-books'
    model = ModelHTTP([
        {'tool_calls': [call('read', {'path': str(skill / 'SKILL.md')}, 'skill')]},
        {'tool_calls': [call('read', {'path': str(skill / 'references/runtime-setup.md')}, 'capabilities')]},
        {'tool_calls': [call('bash', {'command': script + ' build --help'}, 'layout-help')]},
        {'tool_calls': [call('bash', {'command': script + ' init long-story'}, 'init')]},
        {'tool_calls': [call('write', {'path': 'books/long-story/故事与分镜.md', 'content': '小兔抬头，看见一片云。'}, 'story')]},
        {'tool_calls': [call('bash', {'command': 'cd ' + shlex.quote(str(root / 'workspace/books/long-story'))
            + ' && ' + script + ' --project long-story status'}, 'status')]},
        {'content': '故事和项目已经保存。还没有生成插图。'},
        {'tool_calls': [call('read', {'path': 'books/long-story/故事与分镜.md'}, 'resume')]},
        {'content': '前面保存的是小兔看云的故事。'},
    ])
    async def open_agent():
        from cota.policy import train_policy
        await train_policy(root, yaml.safe_load((root / 'agent.yml').read_text())['policy'])
        agent = Agent.load_from_path(str(root))
        adapter = agent.llm_instance('default').client
        # Controlled Python SDK boundary; native streaming is tested separately.
        agent.llm_instance('default').pi_provider = lambda: None
        original = adapter.client
        adapter.client = AsyncOpenAI(api_key='TEST_ONLY', base_url='https://model.example/v1', max_retries=0,
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(model)))
        await original.close()
        return agent
    async def close(agent):
        await agent.cleanup()
        agent.store.engine.dispose()
        agent.user_memory._engine.dispose()

    agent = await open_agent()
    try:
        await agent.create_processor().handle_message(Message(text='开始写故事，先不画图', session_id='book', sender_id='reader', receiver='bot'))
        state = await agent.store.export_session('book')
        assert state['execution']['status'] == 'completed'
        results = [e for e in state['events'] if e['type'] == 'tool_result']
        assert len(results) == 6 and all(e['payload']['status'] == 'success' for e in results)
        layout_help = json.dumps(model.requests[3]['messages'])
        assert 'image_box' in layout_help and 'text_elements' in layout_help
        capability_help = json.dumps(model.requests[2]['messages'], ensure_ascii=False)
        assert 'Cota 绘本 Bot 配套入口' in capability_help
        assert (root / 'workspace/books/long-story/故事与分镜.md').read_text() == '小兔抬头，看见一片云。'
        assert 'Policy: text-only' in model.requests[0]['messages'][0]['content']
        assert model.requests[0]['messages'][0]['content'].count('Policy: ') <= 3
        system_prompt = model.requests[0]['messages'][0]['content']
        assert 'Bot directory: ' + json.dumps(str(root)) in system_prompt
        assert 'Python executable: ' + json.dumps(sys.executable) in system_prompt
        assert '../scripts/book.py' not in system_prompt
        assert 'scripts/book.py' not in system_prompt
        assert 'cota-runtime.md' not in system_prompt
        assert 'picture_book.image' not in system_prompt and 'picture_book.vision' not in system_prompt
        assert not any('PRIVATE_' in json.dumps(request) for request in model.requests)
    finally:
        await close(agent)
    agent = await open_agent()
    try:
        await agent.create_processor().handle_message(Message(text='继续刚才的作品', session_id='book', sender_id='reader', receiver='bot'))
        state = await agent.store.export_session('book')
        restored = await agent.store.load('book', agent=agent)
        assert restored.context_messages == state['context_messages']
        assert [m['content'] for m in model.requests[-1]['messages'] if m['role'] == 'user'] == ['开始写故事，先不画图', '继续刚才的作品']
        assert not model.responses
    finally:
        await close(agent)


def test_picture_book_eval_copy_rebinds_execution_and_keeps_adapters(tmp_path):
    from cota.evaluation.runner import prepare_copy
    target = tmp_path / 'evaluation-copy'
    prepare_copy(BOT, target, BOT / 'policy/eval/data.yml')
    config = yaml.safe_load((target / 'agent.yml').read_text())
    assert (target / config['environment']['workspace']).resolve().is_relative_to(target)
    assert (target / 'bookbot/models.py').is_file()
    assert not (target / 'policy/eval').exists()


def test_generation_timeout_is_not_automatically_repeated(book_modules, book_root):
    pytest.importorskip('PIL')
    root, project = book_root
    (project / 'prompt.txt').write_text('小兔')
    count = 0
    def fail(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout('PRIVATE_IMAGE_KEY', request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        for _ in range(2):
            with pytest.raises(ValueError) as error:
                book_modules['models'].generate(root, project, 'prompt.txt', 'uncertain.png', client=client, asset='test-asset')
            assert 'PRIVATE_' not in str(error.value)
    assert count == 1
    assert json.loads((project / 'uncertain.request.json').read_text())['status'] == 'started'


def test_malformed_endpoints_never_echo_credentials(book_modules, book_root):
    root, _ = book_root
    (root / 'endpoints.yml').write_text('picture_book:\n  image:\n    key: [SENTINEL_SECRET\n')
    for operation in (lambda: book_modules['common'].model_config(root, 'image'),
                      lambda: book_modules['layout'].font_path(root)):
        with pytest.raises(ValueError) as error:
            operation()
        assert 'SENTINEL_SECRET' not in str(error.value)


def test_renderer_invalidates_reviews_when_content_changes(book_modules, book_root):
    pytest.importorskip('PIL')
    pytest.importorskip('reportlab')
    pytest.importorskip('pypdf')
    root, project = book_root
    try:
        book_modules['layout'].font_path(root)
    except ValueError:
        pytest.skip('Optional Chinese font not installed')
    make_book(project)
    book_modules['layout'].build(root, project)
    data = json.loads((project / 'book.json').read_text())
    data['qa'].update(story_reviewed=True, language_reviewed=True,
                      visual_continuity_reviewed=True, pdf_rendered_reviewed=True)
    (project / 'book.json').write_text(json.dumps(data))
    book_modules['layout'].build(root, project)
    assert json.loads((project / 'book.json').read_text())['qa']['pdf_rendered_reviewed'] is True
    data['pages'][4]['text_elements'][0]['text'] = '云朵变成了一只小鸟。'
    (project / 'book.json').write_text(json.dumps(data))
    book_modules['layout'].build(root, project)
    qa = json.loads((project / 'book.json').read_text())['qa']
    assert not qa['language_reviewed'] and not qa['pdf_rendered_reviewed']


def test_validate_refuses_stale_render_even_when_old_qa_claims_pass(book_modules, book_root):
    pytest.importorskip('reportlab')
    pytest.importorskip('pypdf')
    root, project = book_root
    try:
        book_modules['layout'].font_path(root)
    except ValueError:
        pytest.skip('Optional Chinese font not installed')
    make_book(project)
    book_modules['layout'].build(root, project)
    book_modules['layout'].require_current_render(root, project)
    data = json.loads((project / 'book.json').read_text())
    data['pages'][4]['text_elements'][0]['text'] = '这句话还没有排入PDF。'
    (project / 'book.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='rebuild'):
        book_modules['layout'].require_current_render(root, project)


def test_old_pdf_cannot_replace_current_reviewed_deliverable(book_modules, book_root):
    pytest.importorskip('reportlab')
    pytest.importorskip('pypdf')
    root, project = book_root
    try:
        book_modules['layout'].font_path(root)
    except ValueError:
        pytest.skip('Optional Chinese font not installed')
    make_book(project)
    book_modules['layout'].build(root, project)
    (project / 'old.pdf').write_bytes((project / 'book.pdf').read_bytes())
    data = json.loads((project / 'book.json').read_text())
    data['pages'][4]['text_elements'][0]['text'] = '这是新版本的文字。'
    (project / 'book.json').write_text(json.dumps(data))
    book_modules['layout'].build(root, project)
    data = json.loads((project / 'book.json').read_text())
    data['deliverables']['reading_pdf'] = 'old.pdf'
    (project / 'book.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='rebuild'):
        book_modules['layout'].require_current_render(root, project)


@pytest.mark.asyncio
async def test_pi_calls_image_and_vision_services_builds_pdf_and_publishes(book_modules, tmp_path, monkeypatch):
    """Full production path with real provider HTTP and native Pi Bash; fake model content only."""
    import shutil
    import shlex
    import sys
    from aiohttp import web
    from cota.agent import Agent
    from cota.message.message import Message
    from cota.templates import TEMPLATE_IGNORE
    from tests.test_pi_runtime import call
    pytest.importorskip('reportlab')
    pytest.importorskip('pypdf')
    root = tmp_path / 'picture-book'
    shutil.copytree(BOT, root, ignore=TEMPLATE_IGNORE)
    try:
        book_modules['layout'].font_path(root)
    except ValueError:
        pytest.skip('Optional Chinese font not installed')
    project = root / 'workspace/books/example'
    project.mkdir(parents=True)
    make_book(project)
    (project / 'art.png').unlink()
    for attempt in range(1, 4):
        (project / f'archived-{attempt}.request.json').write_text(json.dumps({
            'kind': 'generation', 'asset': 'blocked-page', 'status': 'completed', 'attempt': attempt,
            'input_hash': f'archived-{attempt}', 'output': f'archived-{attempt}.png', 'started_at': attempt}))
    observed, main_requests = [], []
    async def generate(request):
        observed.append('generate')
        assert request.headers['Authorization'] == 'Bearer IMAGE_TEST'
        assert (await request.json())['model'] == 'illustrator-test'
        return web.json_response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    async def edit(request):
        observed.append('edit')
        reader = await request.multipart()
        images = []
        async for field in reader:
            if field.name == 'image[]':
                images.append(await field.read())
        assert images and bytes(images[0]).startswith(b'\x89PNG')
        return web.json_response({'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    async def vision(request):
        body = await request.json()
        if body['model'] == 'main-test':
            assert request.headers['Authorization'] == 'Bearer MAIN_TEST'
            assert body['stream'] is True
            main_requests.append(body)
            reply = sequence.pop(0)
            delta = {'role': 'assistant', 'content': reply.get('content', '')}
            if reply.get('tool_calls'):
                delta['tool_calls'] = [{'index': i, **call} for i, call in enumerate(reply['tool_calls'])]
            frames = [{'id': 'main', 'model': 'main-test', 'object': 'chat.completion.chunk',
                       'choices': [{'index': 0, 'delta': data, 'finish_reason': reason}]}
                      for data, reason in ((delta, None), ({}, 'tool_calls' if reply.get('tool_calls') else 'stop'))]
            return web.Response(text=''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames)
                                + 'data: [DONE]\n\n', content_type='text/event-stream')
        observed.append('vision')
        assert body['model'] == 'vision-test'
        assert any(c.get('type') == 'image_url' for c in body['messages'][0]['content'])
        return web.json_response({'choices': [{'message': {'content': '受控视觉响应：请人工复核，不能认定实际绘画质量。'}}]})
    provider = web.Application()
    provider.router.add_post('/v1/images/generations', generate)
    provider.router.add_post('/v1/images/edits', edit)
    provider.router.add_post('/v1/chat/completions', vision)
    runner = web.AppRunner(provider)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    endpoints = yaml.safe_load((root / 'endpoints.yml').read_text())
    endpoints['llms']['default'].update(key='MAIN_TEST', apibase=f'http://127.0.0.1:{port}/v1', model='main-test')
    endpoints['picture_book']['image'].update(key='IMAGE_TEST', apibase=f'http://127.0.0.1:{port}/v1', model='illustrator-test')
    endpoints['picture_book']['vision'].update(key='VISION_TEST', apibase=f'http://127.0.0.1:{port}/v1', model='vision-test')
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    script = shlex.quote(sys.executable) + ' ' + shlex.quote(str(root / 'scripts/book.py')) + ' --project example '
    sequence = [
        {'tool_calls': [call('read', {'path': str(root / 'skills/creating-childrens-picture-books/SKILL.md')}, 'skill')]},
        {'tool_calls': [call('write', {'path': 'books/example/prompt.txt', 'content': '原创角色，在纯背景下站立，无文字'}, 'prompt')]},
        {'tool_calls': [call('bash', {'command': script + 'generate --asset character-reference --prompt prompt.txt --output character.png', 'timeout': 300}, 'generate')]},
        {'tool_calls': [call('bash', {'command': script + 'generate --asset page-01 --prompt prompt.txt --reference character.png --output art.png', 'timeout': 300}, 'edit')]},
        {'tool_calls': [call('bash', {'command': script + 'generate --asset blocked-page --prompt prompt.txt --output must-not-generate.png', 'timeout': 300}, 'bounded')]},
        {'tool_calls': [call('bash', {'command': script + 'review --asset page-01 --prompt prompt.txt --image art.png --image character.png --output review.json', 'timeout': 300}, 'vision')]},
        {'tool_calls': [call('bash', {'command': script + 'build', 'timeout': 300}, 'pdf')]},
        {'tool_calls': [call('bash', {'command': script + 'deliverables --draft'}, 'deliverables')]},
        {'tool_calls': [call('send_files', {'paths': ['books/example/book.pdf', 'books/example/previews/overview.jpg', 'books/example/打印说明.md'], 'text': '审阅稿，尚未完成内容、视觉与语言验收。'}, 'deliver')]},
        {'content': ''},
    ]
    agent = None
    try:
        from cota.policy import train_policy
        await train_policy(root, yaml.safe_load((root / 'agent.yml').read_text())['policy'])
        agent = Agent.load_from_path(str(root))
        await agent.create_processor().handle_message(Message(text='制作并发布一个审阅稿', session_id='production', sender_id='reader', receiver='bot'))
        assert observed == ['generate', 'edit', 'vision']
        assert len(main_requests) == 10 and not sequence
        session = await agent.store.export_session('production')
        blocked = next(e for e in session['events'] if e['type'] == 'tool_result'
                       and e['payload']['tool_call_id'] == 'bounded')
        assert blocked['payload']['status'] == 'error'
        assert 'revision_limit_reached' in json.dumps(blocked)
        assert not (project / 'must-not-generate.png').exists()
        for request in main_requests:
            assert {'read', 'write', 'edit', 'bash', 'send_files'} <= {
                tool['function']['name'] for tool in request.get('tools', [])}
        assert (project / 'book.pdf').read_bytes().startswith(b'%PDF-')
        events = await agent.store.events('production')
        results = [e for e in events if e['type'] == 'tool_result']
        assert len(results) == 9
        assert sum(e['payload']['status'] == 'success' for e in results) == 8
        assert all(e['payload']['status'] == 'success' for e in results
                   if e['payload']['tool_call_id'] != 'bounded')
        sent = next(e for e in events if e['type'] == 'bot_utter' and e['payload'].get('attachments'))
        assert len(sent['payload']['attachments']) == 3
        assert agent.files.resolve('production', sent['payload']['attachments'][0]['id']).is_file()
        assert 'IMAGE_TEST' not in json.dumps(events) and 'VISION_TEST' not in json.dumps(events)
        assert json.loads((project / 'book.json').read_text())['qa']['pdf_rendered_reviewed'] is False
    finally:
        if agent is not None:
            await agent.cleanup()
            agent.store.engine.dispose()
            agent.user_memory._engine.dispose()
        await runner.cleanup()

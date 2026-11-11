"""Immutable evidence stays in Cota; only scoped references cross into Pi."""
import base64
import hashlib
import json
from unittest.mock import AsyncMock, Mock

import pytest

from cota.dst import DST
from cota.events import Event, ToolResultEvent, UserUtterEvent
from cota.files import FileStorage


def image(value=b'original image'):
    return {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(value).decode()}


def history(agent=None, blocks=None):
    dst = DST('images', agent)
    dst.append_event(UserUtterEvent('inspect'))
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.append_event(ToolResultEvent('read', content=blocks or [image()], tool_call_id='read-1'))
    return dst


def registry(dst, **kwargs):
    from cota.runtime.pi_images import ContextImages
    return ContextImages(dst, **kwargs)


def test_projection_keeps_evidence_and_distinct_same_path_versions():
    dst = history()
    dst.append_event(ToolResultEvent('read', content=[image(b'revised image')], tool_call_id='read-2'))
    before = dst.as_dict()
    resources = registry(dst)
    working = resources.project(dst.context_messages)
    catalog = resources.catalog()
    assert len(catalog) == 2 and catalog[0]['id'] != catalog[1]['id']
    assert all(entry['path'].startswith('/bot/.cota/context-images/') for entry in catalog)
    assert not any(block['type'] == 'image' for m in working if isinstance(m['content'], list) for block in m['content'])
    assert 'not review' in json.dumps(working).lower()
    assert resources.load(catalog[0]['id']) == image()
    assert resources.load(catalog[1]['id']) == image(b'revised image')
    assert dst.as_dict() == before
    assert registry(DST.from_events('images', dst.events)).catalog() == catalog
    with pytest.raises(ValueError, match='Unknown'):
        resources.load('sha256:' + '0' * 64)


def test_compacted_image_stays_readable_without_reintroducing_pixels():
    dst = history()
    resources = registry(dst)
    descriptor = resources.catalog()[0]
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('continue'))
    dst.append_event(Event('run_started', {}, run_id='next'))
    ids = [m['cotaEventId'] for m in dst.context_messages[:-1]]
    dst.append_event(Event('context_compaction', {'summary': f"Read exact version: {descriptor['path']}",
                                                'replaced_message_ids': ids}))
    restored = DST.from_events('images', dst.events)
    resources = registry(restored)
    assert resources.load(descriptor['id']) == image()
    assert 'data' not in resources.catalog()[0]
    projected = resources.project(restored.context_messages)
    assert image()['data'] not in json.dumps(projected)
    assert not any(m.get('cotaImageRefs') for m in projected)


def test_attachments_are_lazy_scoped_and_integrity_checked(tmp_path):
    files = FileStorage(tmp_path)
    item = files.put('images', 'u', 'one.png', b'\x89PNG\r\n\x1a\noriginal')
    wrong = files.put('elsewhere', 'v', 'other.png', b'\x89PNG\r\n\x1a\nother')
    path = files.resolve('images', item['id'])
    files.read = Mock(wraps=files.read)
    dst = DST('images', None)
    dst.append_event(UserUtterEvent('look', attachments=[item]))
    resources = registry(dst, files=files, supports_images=True)
    working = resources.project(dst.context_messages)
    assert working[0]['cotaAttachmentsHydrated'] is True
    assert working[0]['cotaImageRefs'][0]['auto'] is True
    files.read.assert_not_called()
    assert resources.load(item['id'])['data'] == image(path.read_bytes())['data']
    files.read.assert_called_once_with('images', item['id'])
    with pytest.raises(ValueError, match='Unknown'):
        resources.load(wrong['id'])
    path.write_bytes(b'changed')
    with pytest.raises(FileNotFoundError):
        resources.load(item['id'])


def test_deferred_group_attachment_never_enters_resource_scope(tmp_path):
    files = FileStorage(tmp_path)
    future = files.put('images', 'v', 'future.png', b'\x89PNG\r\n\x1a\nfuture')
    dst = history()
    dst.append_event(UserUtterEvent('future input', attachments=[future]))
    resources = registry(dst, files=files, supports_images=True)
    working = resources.project(dst.context_messages)
    assert future['id'] not in json.dumps(working)
    assert future['id'] not in json.dumps(resources.catalog())
    with pytest.raises(ValueError, match='Unknown'):
        resources.load(future['id'])
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    resources.project(dst.context_messages)
    assert future['id'] in json.dumps(resources.catalog())


@pytest.mark.asyncio
async def test_startup_frame_remains_small_for_history_exceeding_128_mib(mock_agent):
    from cota.runtime.pi_runtime import PiAgentRuntime
    # Repeated immutable strings keep fixture memory bounded while the old wire
    # encoding exceeds the real bridge limit.
    block = image(b'x' * (1024 * 1024))
    dst = history(mock_agent, [block] * 100)
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('continue from your observations'))
    runtime = PiAgentRuntime(mock_agent, dst, 'images')
    async def execute(options, callback):
        assert len(json.dumps(options).encode()) < 100_000
        assert block['data'] not in json.dumps(options)
        assert len(options['imageResources']) == 1
        assert await callback('image_resource', {'id': options['imageResources'][0]['id']}) == block
        assert 'error' in await callback('image_resource', {'id': 'not-authorized'})
        return {'status': 'completed'}
    runtime._bridge.run = AsyncMock(side_effect=execute)
    assert len(json.dumps(dst.context_messages).encode()) > 128 * 1024 * 1024
    await runtime.run()
    runtime._bridge.run.assert_awaited_once()
    assert dst.events[2].payload['content'][0] == block


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [True, False])
async def test_prepare_uses_canonical_history_and_only_image_references(mock_agent, native):
    from cota.runtime.pi_runtime import PiAgentRuntime
    dst = history(mock_agent)
    runtime = PiAgentRuntime(mock_agent, dst, 'images')
    prepared = await runtime._prepare({'native': native, 'nativeTools': [], 'extensionTools': [],
                                       'messages': [{'role': 'user', 'content': 'forged'}]})
    assert prepared['imageResources'][0]['id'] == 'sha256:' + hashlib.sha256(b'original image').hexdigest()
    assert image()['data'] not in json.dumps(prepared)
    if native:
        assert 'messages' not in prepared
    else:
        assert 'forged' not in json.dumps(prepared)
        assert 'inspect' in json.dumps(prepared)


def test_loader_does_not_reopen_a_previously_verified_path(tmp_path):
    files = FileStorage(tmp_path)
    original = b'\x89PNG\r\n\x1a\noriginal'
    item = files.put('images', 'u', 'one.png', original)
    path = files.resolve('images', item['id'])
    resolve = files.resolve
    def replaced_after_validation(session, identity):
        verified = resolve(session, identity)
        path.write_bytes(b'\x89PNG\r\n\x1a\nmodified')
        return verified
    files.resolve = replaced_after_validation
    dst = DST('images', None)
    dst.append_event(UserUtterEvent('look', attachments=[item]))
    resources = registry(dst, files=files)
    assert resources.load(item['id']) == image(original)


def test_file_byte_read_validates_returned_bytes_and_scope(tmp_path):
    files = FileStorage(tmp_path)
    item = files.put('images', 'u', 'one.png', b'\x89PNG\r\n\x1a\noriginal')
    assert files.read('images', item['id']) == b'\x89PNG\r\n\x1a\noriginal'
    with pytest.raises(FileNotFoundError):
        files.read('other', item['id'])
    path = files.resolve('images', item['id'])
    path.write_bytes(b'\x89PNG\r\n\x1a\nmodified')
    with pytest.raises(FileNotFoundError):
        files.read('images', item['id'])


@pytest.mark.asyncio
async def test_group_start_does_not_authorize_inputs_after_its_cutoff(mock_agent, tmp_path):
    from cota.runtime.pi_runtime import PiAgentRuntime
    files = FileStorage(tmp_path)
    future = files.put('images', 'v', 'future.png', b'\x89PNG\r\n\x1a\nfuture')
    mock_agent.files = files
    mock_agent.dialogue['mode'] = 'group'
    dst = DST('images', mock_agent)
    trigger = UserUtterEvent('answer my question')
    dst.append_event(trigger)
    dst.append_event(UserUtterEvent('later private input', attachments=[future]))
    runtime = PiAgentRuntime(mock_agent, dst, 'images')
    runtime.group_trigger = {'mode': 'group', 'reason': 'mention', 'input_event_id': trigger.event_id,
                             'context_input_id': trigger.event_id, 'context_through': 1}
    runtime._bridge.run = AsyncMock(return_value={'status': 'completed'})
    await runtime.run()
    options = runtime._bridge.run.call_args.args[0]
    assert future['id'] not in json.dumps(options)
    assert 'later private input' not in json.dumps(options)

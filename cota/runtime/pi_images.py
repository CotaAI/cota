"""Scoped image capabilities for Pi; durable evidence is never rewritten.

Virtual paths are served by Pi's read Operations, not created on disk. Only the
image_resource RPC loads bytes. Policy and DST continue to use original facts.
"""
import base64
from copy import deepcopy
import hashlib
import json

IMAGE_MIMES = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
               'image/gif': 'gif', 'image/bmp': 'bmp'}
AUTO_IMAGE_BYTES = 2 * 1024 * 1024


class ContextImages:
    def __init__(self, dst, *, files=None, supports_images=False, local_files=False):
        self.dst, self.files = dst, files
        self.supports_images, self.local_files = supports_images, local_files
        scope = hashlib.sha256(dst.session_id.encode()).hexdigest()[:32]
        self.root = f'/bot/.cota/context-images/{scope}'
        self._cursor = 0
        self._pending = {}
        self._resources = {}
        self._blocks = {}
        self._positions = {}
        self._encoded = {}

    def _descriptor(self, identity, mime, size):
        return {'id': identity, 'path': f'{self.root}/{identity.replace(":", "-")}.{IMAGE_MIMES[mime]}',
                'mimeType': mime, 'size': size}

    def _sync(self):
        deferred = {m['cotaEventId'] for m in self.dst.context_messages if m.get('cotaDeferred')}
        events = self.dst.events
        for event in [*self._pending.values(), *events[self._cursor:]]:
            if event.event_id in deferred:
                self._pending[event.event_id] = event
                continue
            self._pending.pop(event.event_id, None)
            if event.type == 'tool_result':
                for index, block in enumerate(event.payload.get('content', [])):
                    if block.get('type') != 'image':
                        continue
                    mime, data = block['mimeType'], block['data']
                    if mime not in IMAGE_MIMES:
                        raise ValueError('Unsupported image evidence MIME type')
                    key = (mime, data)
                    if key not in self._encoded:
                        raw = base64.b64decode(data, validate=True)
                        identity = 'sha256:' + hashlib.sha256(raw).hexdigest()
                        descriptor = self._descriptor(identity, mime, len(raw))
                        if identity in self._resources and self._resources[identity] != descriptor:
                            raise ValueError('Immutable image MIME type changed')
                        self._encoded[key] = identity
                        self._resources[identity] = descriptor
                        self._blocks[identity] = {'type': 'image', 'mimeType': mime, 'data': data}
                    self._positions[event.event_id, index] = self._encoded[key]
            if event.type == 'user_utter':
                for item in event.payload.get('attachments', []):
                    if item['mime_type'] in IMAGE_MIMES:
                        self._resources[item['id']] = self._descriptor(item['id'], item['mime_type'], item['size'])
        self._cursor = len(events)

    def catalog(self):
        self._sync()
        return deepcopy(list(self._resources.values()))

    def load(self, identity):
        self._sync()
        if identity not in self._resources:
            raise ValueError('Unknown image resource in this conversation')
        if identity in self._blocks:
            return deepcopy(self._blocks[identity])
        if self.files is None:
            raise FileNotFoundError('Image resource unavailable')
        descriptor = self._resources[identity]
        raw = self.files.read(self.dst.session_id, identity)
        if len(raw) != descriptor['size']:
            raise FileNotFoundError('Image resource size changed')
        return {'type': 'image', 'mimeType': descriptor['mimeType'],
                'data': base64.b64encode(raw).decode()}

    @staticmethod
    def _marker(descriptor, event_id):
        return {'type': 'text', 'text': f'Image pixels omitted (source event {event_id}): '
                + json.dumps(descriptor, ensure_ascii=False, separators=(',', ':'))
                + '. This is not review or approval. Use read(path) to re-read this exact version; '
                  'the virtual resource path is not a filesystem file.'}

    def project(self, messages):
        self._sync()
        result = []
        for original in messages:
            if original.get('cotaDeferred'):
                continue
            message = deepcopy(original)
            refs = []
            content = message['content']
            if isinstance(content, list):
                for index, block in enumerate(content):
                    if block.get('type') == 'image':
                        descriptor = self._resources[self._positions[message['cotaEventId'], index]]
                        content[index] = self._marker(descriptor, message['cotaEventId'])
                        refs.append({'index': index, **descriptor})
            if message.get('cotaAttachments') and not message.get('cotaAttachmentsHydrated'):
                content = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
                for item in message['cotaAttachments']:
                    info = {'attachment_id': item['id'], 'name': item['name']}
                    if self.local_files and self.files is not None:
                        info['local_copy'] = str(self.files.root / item['id'] / 'data')
                    descriptor = self._resources.get(item['id'])
                    if descriptor:
                        auto = self.supports_images and item['size'] <= AUTO_IMAGE_BYTES
                        refs.append({'index': len(content), **descriptor, 'auto': bool(auto)})
                        content.append(self._marker(descriptor, message['cotaEventId']))
                        if not auto:
                            info['note'] = ('Image exceeds automatic model-input limit of 2 MiB; use appropriate image tools.'
                                            if item['size'] > AUTO_IMAGE_BYTES else
                                            'Selected model is not configured for image input; use an appropriate vision tool.')
                    else:
                        info['note'] = 'File contents have not been parsed; use appropriate tools before interpretation.'
                    content.append({'type': 'text', 'text': json.dumps(info, ensure_ascii=False)})
                message['cotaAttachmentsHydrated'] = True
            message['content'] = content
            if refs:
                indexes = {ref['index'] for ref in refs}
                message['content'] = [content[ref['index']] for ref in refs] + [
                    block for index, block in enumerate(content) if index not in indexes]
                message['cotaImageRefs'] = [{**ref, 'index': index} for index, ref in enumerate(refs)]
            result.append(message)
        return result

"""Session-scoped immutable local files, separate from conversation persistence.

Event payloads carry four-field references. Authentication/membership remain the
application's responsibility; this backend enforces the supplied session scope.
"""
from copy import deepcopy
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import stat
import unicodedata
from uuid import uuid4

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 8
FILE_ID = re.compile(r'f_[0-9a-f]{32}')


class UnsupportedAttachments(ValueError):
    """A channel cannot deliver files; retrying the same message cannot fix it."""


def validate_attachments(value):
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENTS:
        raise ValueError('attachments must be a list of at most eight file references')
    ids = set()
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'id', 'name', 'mime_type', 'size'}
                or not isinstance(item['id'], str) or not FILE_ID.fullmatch(item['id'])
                or not isinstance(item['name'], str) or not item['name'] or len(item['name']) > 180
                or any(unicodedata.category(c).startswith('C') or c in '/\\' for c in item['name'])
                or not isinstance(item['mime_type'], str) or not re.fullmatch(r'[\w.+-]+/[\w.+-]+', item['mime_type'])
                or type(item['size']) is not int or not 1 <= item['size'] <= MAX_FILE_BYTES
                or item['id'] in ids):
            raise ValueError('Invalid attachment reference')
        ids.add(item['id'])
    return deepcopy(value)


def _mime(name, data):
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    guessed = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    return 'application/octet-stream' if guessed.startswith('image/') else guessed


class FileStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def put(self, session_id, user_id, name, data):
        if (not isinstance(session_id, str) or not session_id or not isinstance(name, str)
                or not isinstance(data, bytes) or not 1 <= len(data) <= MAX_FILE_BYTES):
            raise ValueError('A file requires a session, name and 1–20 MiB of bytes')
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip(' .')[:180]
        if not name:
            raise ValueError('File name is empty')
        item = {'id': 'f_' + uuid4().hex, 'name': name, 'mime_type': _mime(name, data), 'size': len(data)}
        validate_attachments([item])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        staged = self.root / ('.upload-' + uuid4().hex)
        staged.mkdir(mode=0o700)
        try:
            (staged / 'data').write_bytes(data)
            (staged / 'metadata.json').write_text(json.dumps({**item, 'session_id': session_id,
                'uploader_id': user_id, 'sha256': hashlib.sha256(data).hexdigest()}, ensure_ascii=False), encoding='utf-8')
            os.replace(staged, self.root / item['id'])
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return item

    def _record(self, session_id, file_id):
        try:
            if not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id):
                raise ValueError()
            directory = self.root / file_id
            if directory.is_symlink() or (directory / 'metadata.json').is_symlink():
                raise ValueError()
            record = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
            if record['id'] != file_id or record['session_id'] != session_id:
                raise ValueError()
            validate_attachments([{key: record[key] for key in ('id', 'name', 'mime_type', 'size')}])
            return record
        except (OSError, ValueError, KeyError, TypeError):
            raise FileNotFoundError('File not found in this conversation') from None

    def references(self, session_id, ids):
        if not isinstance(ids, list) or len(ids) > MAX_ATTACHMENTS or any(not isinstance(i, str) for i in ids):
            raise ValueError('Provide at most eight file IDs')
        result = []
        for file_id in ids:
            record = self._record(session_id, file_id)
            result.append({key: record[key] for key in ('id', 'name', 'mime_type', 'size')})
        return validate_attachments(result)

    def read(self, session_id, file_id):
        """Read once and verify the exact bytes returned to the caller."""
        record = self._record(session_id, file_id)
        path = self.root / file_id / 'data'
        try:
            if path.is_symlink():
                raise ValueError()
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != record['size']:
                    raise ValueError()
                data = stream.read(record['size'] + 1)
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError()
        except (OSError, ValueError, KeyError):
            raise FileNotFoundError('File unavailable or modified') from None
        return data

    def resolve(self, session_id, file_id):
        self.read(session_id, file_id)
        return self.root / file_id / 'data'

    def named_copy(self, session_id, file_id):
        """A local viewing copy with its original filename; never the evidence.

        OS viewers use filename extensions. Keep their editable copy separate
        from immutable bytes used for history/downloads, and retain local edits.
        """
        source = self.resolve(session_id, file_id)
        record = self._record(session_id, file_id)
        directory = source.parent / 'view'
        if directory.is_symlink() or directory.exists() and not directory.is_dir():
            raise FileNotFoundError('Attachment viewing directory is unavailable')
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / record['name']
        if target.parent != directory or target.is_symlink():
            raise FileNotFoundError('Attachment viewing copy is unavailable')
        if target.exists():
            if (not target.is_file() or target.stat().st_size != record['size']
                    or hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']):
                raise FileNotFoundError('Local viewing copy was modified; save it elsewhere before reopening')
            return target
        staged = directory / ('.view-' + uuid4().hex)
        try:
            data = source.read_bytes()
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise FileNotFoundError('Attachment changed while preparing its viewing copy')
            staged.write_bytes(data)
            os.chmod(staged, 0o600)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        return target

    def import_paths(self, session_id, user_id, workspace, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_ATTACHMENTS:
            raise ValueError('Provide one to eight workspace file paths')
        root = Path(workspace).resolve()
        prepared = []
        for value in paths:
            if not isinstance(value, str) or not value:
                raise ValueError('File path must be nonempty text')
            path = Path(os.path.abspath(root / value))
            if (not path.is_relative_to(root) or path == root
                    or any(p.is_symlink() for p in (path, *path.parents) if p == root or root in p.parents)):
                raise ValueError('Files must be inside the workspace without symlinks')
            try:
                if not stat.S_ISREG(path.stat().st_mode) or not 1 <= path.stat().st_size <= MAX_FILE_BYTES:
                    raise ValueError('Export requires a regular file of 1–20 MiB')
                with path.open('rb') as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError('File exceeds 20 MiB')
            except OSError:
                raise ValueError('Workspace file is unavailable') from None
            prepared.append((path.name, data))
        return [self.put(session_id, user_id, name, data) for name, data in prepared]

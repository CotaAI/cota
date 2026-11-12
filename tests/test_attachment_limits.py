"""Attachment capabilities and precise export failures, without model calls."""
from pathlib import Path

import pytest

import cota.files as module
from cota.files import FileStorage


def test_capabilities_match_current_backend_limits_and_are_detached(tmp_path, monkeypatch):
    files = FileStorage(tmp_path / 'stored')
    assert files.capabilities() == {'max_file_bytes': 20 * 1024 * 1024, 'max_attachments': 8}
    capabilities = files.capabilities()
    capabilities['max_file_bytes'] = 1
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 1024)
    monkeypatch.setattr(module, 'MAX_ATTACHMENTS', 2)
    assert files.capabilities() == {'max_file_bytes': 1024, 'max_attachments': 2}


def assert_failure(error, *, reason, file=None, actual_bytes=None):
    assert isinstance(error, module.FileExportError)
    assert error.details['reason'] == reason
    assert error.details['retryable'] is False
    assert error.details['next']
    if file is not None:
        assert error.details['file'] == file
        assert not Path(error.details['file']).is_absolute()
    if actual_bytes is not None:
        assert error.details['actual_bytes'] == actual_bytes
    assert error.details['max_file_bytes'] == module.MAX_FILE_BYTES


def test_audited_pdf_size_reports_exact_excess_before_reading_or_importing(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    path = workspace / 'book.pdf'
    size = 20 * 1024 * 1024 + 85085
    with path.open('wb') as stream:
        stream.truncate(size)
    files = FileStorage(tmp_path / 'stored')
    monkeypatch.setattr(files, 'put', lambda *args: pytest.fail('Preflight must reject before importing'))
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('Oversized files must not be read'))
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', workspace, ['book.pdf'])
    assert_failure(error.value, reason='file_too_large', file='book.pdf', actual_bytes=size)
    assert str(size) in str(error.value)
    assert not files.root.exists()


@pytest.mark.parametrize('kind,reason,size', [('missing', 'file_missing', None),
                                           ('directory', 'not_regular_file', None),
                                           ('empty', 'file_empty', 0)])
def test_missing_nonregular_and_empty_files_have_distinct_outcomes(tmp_path, kind, reason, size):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    path = workspace / 'source'
    if kind == 'directory':
        path.mkdir()
    elif kind == 'empty':
        path.touch()
    files = FileStorage(tmp_path / 'stored')
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', workspace, ['source'])
    assert_failure(error.value, reason=reason, file='source', actual_bytes=size)
    assert not files.root.exists()


def test_exact_maximum_is_accepted_and_one_extra_byte_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 16)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'exact.txt').write_bytes(b'x' * 16)
    (workspace / 'large.txt').write_bytes(b'x' * 17)
    files = FileStorage(tmp_path / 'stored')
    item = files.import_paths('s', 'u', workspace, ['exact.txt'])[0]
    assert files.read('s', item['id']) == b'x' * 16
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', workspace, ['large.txt'])
    assert_failure(error.value, reason='file_too_large', file='large.txt', actual_bytes=17)


@pytest.mark.parametrize('bad', ['missing.pdf', 'empty.pdf', 'large.pdf', 'directory'])
def test_batch_preflight_does_not_import_earlier_valid_files(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 16)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'good.txt').write_bytes(b'valid')
    (workspace / 'empty.pdf').touch()
    (workspace / 'large.pdf').write_bytes(b'x' * 17)
    (workspace / 'directory').mkdir()
    files = FileStorage(tmp_path / 'stored')
    with pytest.raises(ValueError):
        files.import_paths('s', 'u', workspace, ['good.txt', bad])
    assert not files.root.exists()


def test_symlink_and_outside_paths_remain_denied_without_exposing_absolute_paths(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'private.key'
    outside.write_bytes(b'PRIVATE_CONTENT_MUST_NOT_APPEAR')
    (workspace / 'link').symlink_to(outside)
    files = FileStorage(tmp_path / 'stored')
    for path in ('link', '../private.key', str(outside)):
        with pytest.raises(ValueError) as error:
            files.import_paths('s', 'u', workspace, [path])
        assert_failure(error.value, reason='outside_workspace')
        assert 'PRIVATE_CONTENT' not in str(error.value)
        assert str(tmp_path) not in str(error.value)
    assert not files.root.exists()


def test_bad_count_advertises_the_actual_batch_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MAX_ATTACHMENTS', 2)
    files = FileStorage(tmp_path / 'stored')
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', tmp_path, ['a', 'b', 'c'])
    assert_failure(error.value, reason='attachment_count_invalid')
    assert error.value.details['max_attachments'] == 2
    assert error.value.details['actual_count'] == 3


def test_failed_batch_storage_rolls_back_only_its_new_files(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'first.txt').write_bytes(b'first')
    (workspace / 'second.txt').write_bytes(b'second')
    files = FileStorage(tmp_path / 'stored')
    existing = files.put('s', 'u', 'previous.txt', b'keep')
    original = files.put
    def put(session, user, name, data):
        if name == 'second.txt':
            raise OSError('Controlled failure')
        return original(session, user, name, data)
    monkeypatch.setattr(files, 'put', put)
    with pytest.raises(OSError):
        files.import_paths('s', 'u', workspace, ['first.txt', 'second.txt'])
    assert sorted(p.name for p in files.root.iterdir()) == [existing['id']]
    assert files.read('s', existing['id']) == b'keep'


def test_invalid_export_filename_is_rejected_before_any_batch_write(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'good.txt').write_bytes(b'good')
    (workspace / '...').write_bytes(b'bad name')
    files = FileStorage(tmp_path / 'stored')
    monkeypatch.setattr(files, 'put', lambda *args: pytest.fail('Invalid name must fail during preflight'))
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', workspace, ['good.txt', '...'])
    assert_failure(error.value, reason='file_name_invalid', file='...')
    assert not files.root.exists()


def test_nul_path_returns_a_structured_invalid_path_without_io(tmp_path):
    files = FileStorage(tmp_path / 'stored')
    with pytest.raises(ValueError) as error:
        files.import_paths('s', 'u', tmp_path, ['bad\0file'])
    assert_failure(error.value, reason='file_path_invalid')
    assert not files.root.exists()

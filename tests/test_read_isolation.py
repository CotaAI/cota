"""A session restore must not combine metadata and snapshots from different commits."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cota.store import SQLStore


@pytest.mark.parametrize('dialect', ['mysql', 'postgresql'])
def test_restore_sets_repeatable_read_before_starting_transaction(tmp_path, dialect):
    store = SQLStore(db=str(tmp_path / 'store.db'))
    real_engine = store.engine
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execution_options.return_value = connection
    connection.in_transaction.return_value = False
    connection.execute.return_value.mappings.return_value.first.return_value = None
    store.engine = SimpleNamespace(dialect=SimpleNamespace(name=dialect), connect=lambda: connection)
    try:
        assert store._read_sync('missing') is None
        names = [call[0] for call in connection.mock_calls]
        assert names.index('execution_options') < names.index('begin') < names.index('execute')
        connection.execution_options.assert_called_once_with(isolation_level='REPEATABLE READ')
    finally:
        real_engine.dispose()

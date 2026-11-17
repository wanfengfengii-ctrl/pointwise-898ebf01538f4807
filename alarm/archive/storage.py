import sqlite3
from contextlib import contextmanager
from alarm.archive.schema import initialize_schema


class ArchiveStorageError(RuntimeError):
    pass


class ArchiveStore:
    def __init__(self, connection):
        self.connection = connection
        self._closed = False

    @classmethod
    def open(cls, path=':memory:'):
        connection = sqlite3.connect(str(path), isolation_level=None)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=5000')
            initialize_schema(connection)
        except BaseException:
            connection.close()
            raise
        return cls(connection)

    @contextmanager
    def transaction(self):
        if self._closed or self.connection.in_transaction:
            raise ArchiveStorageError('closed store or nested transaction')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

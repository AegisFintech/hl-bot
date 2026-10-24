"""Short-lived SQLite transactions with deterministic connection cleanup."""

from contextlib import contextmanager
import sqlite3


@contextmanager
def transaction(path, *, timeout=5, rows=False):
    connection = sqlite3.connect(str(path), timeout=timeout)
    if rows:
        connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()

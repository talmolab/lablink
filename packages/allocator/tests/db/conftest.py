"""Shared fixtures for tests/db/*.

`mock_db_connection`/`db_instance` build a `VmDatabase` wired to a
mocked pool via dependency injection (`VmDatabase(..., pool=...)`),
not by mocking `psycopg2` in `sys.modules`. That used to be necessary
because `__init__` called `psycopg2.pool.ThreadedConnectionPool(...)`
directly, so tests had to intercept it. Now that construction is skippable
via `pool=`, no interception is needed, `db.vms`/`db.pool` import normally
(once, real-bound, like any other module), and correctness no longer
depends on collection order or which module's `import psycopg2` a given
test happened to capture — the two-instances-of-db.pool bug this replaced
is structurally impossible once no test needs the module-level psycopg2
mock for construction.

`VmDatabase` is a plain, ordinary import here (no `sys.modules`
patching), since nothing needs psycopg2 mocked anymore.
"""
from unittest.mock import MagicMock

import pytest

from lablink_allocator_service.db.vms import VmDatabase
from lablink_allocator_service.db.schedules import ScheduleDatabase


@pytest.fixture
def mock_db_connection():
    """Fixture returning (mock_conn, mock_cursor, mock_pool).

    - mock_pool.getconn() returns mock_conn.
    - mock_conn.cursor() returns mock_cursor directly.

    Tests that previously reassigned db.conn and db.cursor after
    instantiation continue to work via the convenience aliases set in
    db_instance below.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    # conn.cursor() returns the cursor directly (real psycopg2 behavior).
    # PooledCursor calls conn.cursor() and uses the result as the cursor.
    mock_conn.cursor.return_value = mock_cursor

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn

    return mock_conn, mock_cursor, mock_pool


@pytest.fixture
def db_instance(mock_db_connection):
    """Fixture returning a VmDatabase wired to a mocked pool."""
    mock_conn, mock_cursor, mock_pool = mock_db_connection
    db = VmDatabase(
        dbname="testdb",
        user="testuser",
        password="testpassword",
        host="localhost",
        port=5432,
        table_name="vms",
        pool=mock_pool,
    )
    # Convenience aliases so test bodies can keep using db_instance.cursor
    # and db_instance.conn without knowing about pool internals.
    db.conn = mock_conn
    db.cursor = mock_cursor
    return db


@pytest.fixture
def db_with_mock_cursor(db_instance, mock_db_connection):
    """(VmDatabase, mock cursor) tuple for tests that destructure both at
    once instead of pulling mock_cursor out of mock_db_connection."""
    _, mock_cursor, _ = mock_db_connection
    return db_instance, mock_cursor


@pytest.fixture
def schedule_db_instance(mock_db_connection):
    """A ScheduleDatabase over the same mocked pool as db_instance."""
    mock_conn, mock_cursor, mock_pool = mock_db_connection
    db = ScheduleDatabase(pool=mock_pool)
    # The relocated tests read db.cursor directly, matching db_instance.
    db.cursor = mock_cursor
    return db

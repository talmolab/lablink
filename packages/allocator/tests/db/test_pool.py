import psycopg2
import pytest
from unittest.mock import patch

from lablink_allocator_service.db.vms import VmDatabase


class _Cfg:
    """Stand-in for cfg.db — only the attributes make_pool reads."""

    dbname = "testdb"
    user = "testuser"
    password = "testpass"
    host = "localhost"
    port = 5432


def test_make_pool_passes_connection_params():
    with patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool:
        from lablink_allocator_service.db.pool import make_pool

        make_pool(_Cfg(), pool_min_size=2, pool_max_size=10)

    mock_pool.assert_called_once_with(
        minconn=2,
        maxconn=10,
        dbname="testdb",
        user="testuser",
        password="testpass",
        host="localhost",
        port=5432,
    )


def test_make_pool_rejects_min_below_one():
    from lablink_allocator_service.db.pool import make_pool

    with pytest.raises(ValueError, match="Invalid pool sizes"):
        make_pool(_Cfg(), pool_min_size=0, pool_max_size=10)


def test_make_pool_rejects_max_below_min():
    from lablink_allocator_service.db.pool import make_pool

    with pytest.raises(ValueError, match="Invalid pool sizes"):
        make_pool(_Cfg(), pool_min_size=5, pool_max_size=2)


def test_validate_pool_sizes_accepts_valid_sizes():
    """No exception, no return value, for well-formed sizes. Also confirms
    validate_pool_sizes touches no psycopg2 — no mock is patched here."""
    from lablink_allocator_service.db.pool import validate_pool_sizes

    assert validate_pool_sizes(2, 200) is None
    assert validate_pool_sizes(1, 1) is None


def test_validate_pool_sizes_rejects_min_below_one():
    from lablink_allocator_service.db.pool import validate_pool_sizes

    with pytest.raises(ValueError, match="Invalid pool sizes"):
        validate_pool_sizes(0, 10)


def test_validate_pool_sizes_rejects_max_below_min():
    from lablink_allocator_service.db.pool import validate_pool_sizes

    with pytest.raises(ValueError, match="Invalid pool sizes"):
        validate_pool_sizes(5, 2)


def test_pool_size_validation_rejects_min_zero():
    """pool_min_size must be >= 1."""
    with pytest.raises(ValueError, match="Invalid pool sizes"):
        VmDatabase(
            dbname="testdb",
            user="testuser",
            password="testpassword",
            host="localhost",
            port=5432,
            table_name="vms",
            pool_min_size=0,
            pool_max_size=5,
        )


def test_pool_size_validation_rejects_max_below_min():
    """pool_max_size must be >= pool_min_size."""
    with pytest.raises(ValueError, match="Invalid pool sizes"):
        VmDatabase(
            dbname="testdb",
            user="testuser",
            password="testpassword",
            host="localhost",
            port=5432,
            table_name="vms",
            pool_min_size=5,
            pool_max_size=2,
        )


def test_pool_max_size_env_override_parses_int(monkeypatch):
    from lablink_allocator_service.db.pool import _pool_max_size_from_env

    monkeypatch.setenv("LABLINK_DB_POOL_MAX_SIZE", "120")
    assert _pool_max_size_from_env(default=60) == 120


def test_pool_max_size_env_override_unset_returns_default(monkeypatch):
    from lablink_allocator_service.db.pool import _pool_max_size_from_env

    monkeypatch.delenv("LABLINK_DB_POOL_MAX_SIZE", raising=False)
    assert _pool_max_size_from_env(default=60) == 60


def test_pool_max_size_env_override_invalid_falls_back(monkeypatch, caplog):
    from lablink_allocator_service.db.pool import _pool_max_size_from_env

    monkeypatch.setenv("LABLINK_DB_POOL_MAX_SIZE", "not-a-number")
    with caplog.at_level("WARNING"):
        assert _pool_max_size_from_env(default=60) == 60
    assert "Ignoring invalid LABLINK_DB_POOL_MAX_SIZE" in caplog.text


def test_pool_max_size_env_override_nonpositive_falls_back(monkeypatch, caplog):
    from lablink_allocator_service.db.pool import _pool_max_size_from_env

    monkeypatch.setenv("LABLINK_DB_POOL_MAX_SIZE", "0")
    with caplog.at_level("WARNING"):
        assert _pool_max_size_from_env(default=60) == 60
    assert "Ignoring LABLINK_DB_POOL_MAX_SIZE=0" in caplog.text


def test_cursor_returns_connection_on_success(db_instance):
    """After a successful `with self._cursor` block, the pool's
    putconn is called once with close=False."""
    mock_pool = db_instance._pool
    with db_instance._cursor as cur:
        cur.execute("SELECT 1;")
    mock_pool.putconn.assert_called_once()
    # close defaults to False on success; verify via kwargs or positional
    _, kwargs = mock_pool.putconn.call_args
    assert kwargs.get("close", False) is False


def test_cursor_discards_connection_on_exception(db_instance):
    """If a query raises, putconn is called with close=True so the bad
    connection is evicted from the pool."""
    mock_pool = db_instance._pool
    db_instance.cursor.execute.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        with db_instance._cursor as cur:
            cur.execute("SELECT 1;")
    mock_pool.putconn.assert_called_once()
    _, kwargs = mock_pool.putconn.call_args
    assert kwargs.get("close") is True


def test_cursor_sets_autocommit_per_checkout(db_instance):
    """Every checkout applies ISOLATION_LEVEL_AUTOCOMMIT, preserving
    the pre-refactor per-statement-transaction behavior.

    psycopg2 is not mocked anywhere in this test suite anymore (db_instance
    injects a MagicMock pool via VmDatabase(..., pool=...)), so
    this asserts against the real psycopg2.extensions constant — the same
    module-level `psycopg2` that db/pool.py's PooledCursor itself uses,
    since there is now exactly one db.pool module for the whole session.
    """
    mock_conn = db_instance.conn
    mock_conn.set_isolation_level.reset_mock()
    with db_instance._cursor:
        pass
    mock_conn.set_isolation_level.assert_called_once_with(
        psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
    )

"""Connection-pool primitives shared by every class in this package.

Kept separate from the persistence classes so that importing pool
machinery never pulls in a module that opens connections or defines
table-specific SQL.
"""
from __future__ import annotations

import logging
import os

import psycopg2
import psycopg2.pool

logger = logging.getLogger(__name__)


def _pool_max_size_from_env(default: int) -> int:
    """LABLINK_DB_POOL_MAX_SIZE override, clamped to >= POOL_MIN_SIZE.
    Invalid/missing values fall through to the default."""
    raw = os.environ.get("LABLINK_DB_POOL_MAX_SIZE")
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring invalid LABLINK_DB_POOL_MAX_SIZE=%r; using %d", raw, default
        )
        return default
    if parsed < 1:
        logger.warning(
            "Ignoring LABLINK_DB_POOL_MAX_SIZE=%d (<1); using %d", parsed, default
        )
        return default
    return parsed


# Pool sizing. Default sized for ~100 client VMs polling concurrently
# plus the admin UI; start.sh raises Postgres max_connections in lockstep.
# Override at deploy time with LABLINK_DB_POOL_MAX_SIZE without rebuilding
# the image (keep it below max_connections minus autovacuum/admin headroom).
POOL_MIN_SIZE = 2
POOL_MAX_SIZE = _pool_max_size_from_env(default=200)


class PooledCursor:
    """Checks out an autocommit connection from the pool, opens a cursor,
    and returns both to the pool/closes on exit. Preserves the per-call
    context-manager API previously provided by _LockedCursor.
    """

    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        self._cur = None

    def __enter__(self):
        self._conn = self._pool.getconn()
        try:
            # Mirror pre-refactor behavior: every connection runs in
            # autocommit. Applied per checkout — cheap, and defensive
            # against anything that ever flips isolation levels on a
            # pooled conn.
            self._conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
            )
            self._cur = self._conn.cursor()
            return self._cur
        except Exception:
            self._pool.putconn(self._conn)
            self._conn = None
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._cur is not None:
                self._cur.close()
        finally:
            if self._conn is not None:
                # On exception, discard the conn so a bad connection doesn't
                # re-enter the pool. Happy path: return it for reuse.
                self._pool.putconn(
                    self._conn, close=(exc_type is not None)
                )
        return False  # don't swallow exceptions


def validate_pool_sizes(pool_min_size: int, pool_max_size: int) -> None:
    """Reject invalid pool sizing. Pure — deliberately touches no psycopg2.

    Callers that build their own pool (VmDatabase.__init__) use this instead
    of make_pool, so that pool CONSTRUCTION stays inside the caller's module.
    A module-level `import psycopg2` binds the module object at import time,
    so whichever module actually builds the pool is the one whose binding of
    psycopg2 gets exercised. Keeping construction in VmDatabase rather than
    delegating it to a helper here keeps that binding local to VmDatabase —
    and therefore substitutable per-instance, e.g. by dependency-injecting a
    pre-built pool via the `pool` constructor argument instead of needing to
    intercept psycopg2 itself.

    Raises:
        ValueError: If pool sizing is invalid.
    """
    if pool_min_size < 1 or pool_max_size < pool_min_size:
        raise ValueError(
            f"Invalid pool sizes: min={pool_min_size}, max={pool_max_size}"
        )


def make_pool(cfg_db, *, pool_min_size=POOL_MIN_SIZE, pool_max_size=POOL_MAX_SIZE):
    """Build a ThreadedConnectionPool from a `cfg.db`-shaped object.

    For callers that need ONLY a pool and no persistence class — e.g. the
    APScheduler job in scheduler.py, which shares one pool across several
    handles. The pool is built with THIS module's psycopg2 binding; a caller
    that needs the binding to be its own (see validate_pool_sizes) should
    construct the pool itself rather than calling this.

    Raises:
        ValueError: If pool sizing is invalid.
    """
    validate_pool_sizes(pool_min_size, pool_max_size)
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=pool_min_size,
        maxconn=pool_max_size,
        dbname=cfg_db.dbname,
        user=cfg_db.user,
        password=cfg_db.password,
        host=cfg_db.host,
        port=cfg_db.port,
    )

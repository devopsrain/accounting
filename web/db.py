"""
PostgreSQL Database Connection Module

Provides a thread-safe connection pool for all data stores.
Reads DATABASE_URL from environment (set in .env or os.environ).

Usage:
    from db import get_conn, get_cursor

    # Single query
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()

    # Multiple queries in one transaction
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO ...")
            cur.execute("UPDATE ...")
"""

import os
import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


def _init_pool():
    """Initialize the connection pool (called lazily on first use)."""
    global _pool
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Add it to your .env file or set it in the environment."
        )
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=20,
        dsn=database_url,
        connect_timeout=10,
    )
    logger.info("PostgreSQL connection pool initialised (min=2, max=20)")


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return (or lazily create) the connection pool."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:          # double-checked locking
                _init_pool()
    return _pool


@contextmanager
def get_conn():
    """
    Context manager that checks out a connection, commits on clean exit,
    rolls back on exception, then returns the connection to the pool.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor():
    """
    Convenience context manager that yields a RealDictCursor.
    Wraps get_conn(), so commit/rollback is handled automatically.
    """
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()


def execute(sql: str, params=None):
    """
    Execute a single DML statement (INSERT / UPDATE / DELETE).
    Returns the cursor's rowcount.
    """
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def fetchone(sql: str, params=None) -> dict | None:
    """Run a SELECT and return the first row as a dict, or None."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetchall(sql: str, params=None) -> list[dict]:
    """Run a SELECT and return all rows as a list of dicts."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def health_check() -> bool:
    """Return True if the database is reachable."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return False

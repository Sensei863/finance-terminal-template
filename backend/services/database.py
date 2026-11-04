import os
import threading
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
import logging
import time
import warnings

warnings.filterwarnings('ignore', category=UserWarning, message='.*pandas only supports SQLAlchemy connectable.*')

logger = logging.getLogger(__name__)

# Connection pools (lazily initialised)
_ledger_pool = None
_app_pool = None
_pool_lock = threading.Lock()

def _make_pool(url: str, name: str, maxconn: int = 3):
    """
    Create a ThreadedConnectionPool with options suitable for PgBouncer
    in transaction-pooling mode (Supabase port 6543).

    Key settings:
    - minconn=0  → do NOT open connections on pool creation; avoids
                   the startup 'server didn't return client encoding' failure
                   that happens when PgBouncer is momentarily overloaded.
    - keepalives → detect dead TCP connections quickly so they are not
                   recycled back into the pool.
    - options=-c search_path=public  → safe session-level param that
                   PgBouncer allows even in transaction mode.
    """
    # Build extra kwargs for keepalives and search_path
    extra_kwargs = dict(
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        # options removed: Neon's PgBouncer pooler rejects ALL startup parameters

    )
    try:
        p = pool.ThreadedConnectionPool(0, maxconn, url, **extra_kwargs)
        logger.info("Initialized %s ThreadedConnectionPool (size 0-%d)", name, maxconn)
        return p
    except Exception as e:
        logger.error("Failed to initialize %s pool: %s", name, e)
        return None


def _init_pools():
    global _ledger_pool, _app_pool
    # Fast path without lock
    if _ledger_pool is not None and _app_pool is not None:
        return

    with _pool_lock:
        if _ledger_pool is None:
            ledger_url = os.getenv("LEDGER_DATABASE_URL") or os.getenv("DATABASE_URL")
            if ledger_url:
                _ledger_pool = _make_pool(ledger_url, "Ledger DB", maxconn=30)
            else:
                logger.warning("LEDGER_DATABASE_URL and DATABASE_URL not found in environment.")

        if _app_pool is None:
            app_url = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
            if app_url:
                _app_pool = _make_pool(app_url, "App DB", maxconn=30)
            else:
                logger.warning("APP_DATABASE_URL or DATABASE_URL not found in environment.")


def _checkout_with_retry(p, pool_name: str, retries: int = 10):
    """
    Try to check out a connection, retrying a few times if pool is exhausted.
    """
    for attempt in range(retries):
        try:
            conn = p.getconn()
            # Quick liveness check — poll() is cheap and non-blocking
            conn.poll()
            if conn.closed:
                raise psycopg2.OperationalError("Connection is closed")
            return conn
        except pool.PoolError as e:
            if attempt < retries - 1:
                time.sleep(1.0)
            else:
                raise RuntimeError(f"{pool_name} connection pool exhausted after {retries} retries: {e}")
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            logger.warning(
                "Dead connection from %s pool (attempt %d/%d): %s — discarding",
                pool_name, attempt + 1, retries, e,
            )
            # If we got a connection, discard it
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            if attempt == retries:
                raise
    raise psycopg2.OperationalError(f"Could not obtain a live connection from {pool_name} pool")


@contextmanager
def get_ledger_connection():
    """Yields a live connection from the Ledger DB pool."""
    if _ledger_pool is None:
        _init_pools()
    if _ledger_pool is None:
        raise RuntimeError("Ledger DB connection pool is not initialized.")

    conn = _checkout_with_retry(_ledger_pool, "Ledger DB")
    closed_by_us = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        try:
            _ledger_pool.putconn(conn, close=True)
            closed_by_us = True
            logger.warning("Discarded dead connection from Ledger DB pool.")
        except Exception:
            pass
        raise
    finally:
        if not closed_by_us:
            try:
                conn.rollback()          # always rollback uncommitted work
                _ledger_pool.putconn(conn)
            except Exception:
                pass


@contextmanager
def get_app_connection():
    """Yields a live connection from the App DB pool."""
    if _app_pool is None:
        _init_pools()
    if _app_pool is None:
        raise RuntimeError("App DB connection pool is not initialized.")

    conn = _checkout_with_retry(_app_pool, "App DB")
    closed_by_us = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        try:
            _app_pool.putconn(conn, close=True)
            closed_by_us = True
            logger.warning("Discarded dead connection from App DB pool.")
        except Exception:
            pass
        raise
    finally:
        if not closed_by_us:
            try:
                conn.rollback()          # always rollback uncommitted work
                _app_pool.putconn(conn)
            except Exception:
                pass

from app.core.config import settings

# Postgres (psycopg2) imports
from typing import Optional
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
import psycopg2

_pg_pool: Optional[SimpleConnectionPool] = None


# ==============================
# Psycopg2 connection utilities
# ==============================
def _build_conninfo(url: str) -> str:
    """Ensure sslmode=require is present for Supabase-hosted Postgres connections."""
    if not url:
        raise ValueError("DATABASE_URL is not set")
    # If sslmode already specified, return as-is
    if "sslmode=" in url:
        return url
    # Append sslmode=require respecting existing query string
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}sslmode=require"


def get_pg_pool(minconn: int = 1, maxconn: int = 5) -> SimpleConnectionPool:
    """Lazily initialize and return a global psycopg2 connection pool."""
    global _pg_pool
    if _pg_pool is None:
        conninfo = _build_conninfo(settings.database_url)
        _pg_pool = SimpleConnectionPool(minconn=minconn, maxconn=maxconn, dsn=conninfo)
    return _pg_pool


@contextmanager
def pg_connection():
    """Context manager that yields a pooled psycopg2 connection."""
    pool = get_pg_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def pg_cursor(commit: bool = False):
    """Context manager for a psycopg2 cursor. Optionally commits on exit.

    Usage:
        with pg_cursor(commit=True) as cur:
            cur.execute("SELECT 1")
    """
    with pg_connection() as conn:
        with conn.cursor() as cur:
            yield cur
            if commit:
                conn.commit()


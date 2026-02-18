import os
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_NAME = os.environ.get("DB_NAME", "nelsonquiz")
DB_USER = os.environ.get("DB_USER", "nelsonuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "nelson2024xyz")

# Connection pool configuration
MIN_CONN = int(os.environ.get("DB_MIN_CONN", "2"))
MAX_CONN = int(os.environ.get("DB_MAX_CONN", "10"))

# Create connection pool
_db_pool = None

def init_db_pool():
    """Initialize the database connection pool."""
    global _db_pool
    if _db_pool is None:
        try:
            _db_pool = psycopg2.pool.ThreadedConnectionPool(
                MIN_CONN,
                MAX_CONN,
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                cursor_factory=RealDictCursor
            )
        except psycopg2.Error as e:
            raise RuntimeError(f"Failed to create database connection pool: {e}")
    return _db_pool

def get_db():
    """
    Get a database connection from the pool.
    Returns a connection object.
    Raises RuntimeError if connection fails.
    """
    pool = init_db_pool()
    try:
        conn = pool.getconn()
        if conn is None:
            raise RuntimeError("Failed to get connection from pool")
        return conn
    except psycopg2.Error as e:
        raise RuntimeError(f"Database connection error: {e}")

@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Automatically returns connection to pool and handles errors.
    
    Usage:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users")
            results = cur.fetchall()
            conn.commit()
    """
    conn = None
    try:
        conn = get_db()
        yield conn
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise RuntimeError(f"Database error: {e}")
    finally:
        if conn:
            pool = init_db_pool()
            pool.putconn(conn)

def close_db_pool():
    """Close all connections in the pool. Call this on application shutdown."""
    global _db_pool
    if _db_pool:
        _db_pool.closeall()
        _db_pool = None

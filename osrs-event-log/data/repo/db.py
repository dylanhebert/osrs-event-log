"""Connection management for the SQLite store.

Deliberately uses the stdlib sqlite3 rather than aiosqlite. The repo functions
are plain (non-async) and are called from `async def` handlers, which means they
block the event loop — but only for the microseconds a local SQLite query takes.
The code being replaced did a blocking json.load() of a 470 KB file inside an
`async def` on every single handler call, so this is strictly less blocking than
the status quo, and it avoids adding a dependency to a project that already
carries 36 dependabot alerts.

One process, one event loop (the looper and the Dink webhook share it), so one
module-level connection is enough. WAL is on so that a reader — a future
read-only web UI on port 8007 — never blocks the bot's writes.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join("data", "osrs.db")
DEFAULT_SCHEMA_PATH = os.path.join("data", "schema.sql")

_conn = None
_path = None
_lock = threading.RLock()


def utcnow():
    """Timestamps are UTC ISO8601. The bot's SOTW/BOTW scheduling uses local
    time (datetime.now()) because its deadlines are expressed in CST, but that
    is presentation; rows recording *when something happened* are UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=None, schema_path=None, create=True):
    """Open (or create) the database. Idempotent."""
    global _conn, _path
    with _lock:
        if _conn is not None:
            # Reconnect when an explicit, different path is asked for. Without
            # this a test that opens a scratch database silently keeps the
            # connection the bot's handlers already opened to the live one —
            # importing data.handlers is enough to trigger that, because
            # sotw.py reads its config at import time.
            if path is None or os.path.abspath(path) == os.path.abspath(_path or ""):
                return _conn
            _conn.close()
            _conn, _path = None, None

        path = path or DEFAULT_DB_PATH
        schema_path = schema_path or DEFAULT_SCHEMA_PATH
        fresh = not os.path.exists(path)
        if fresh and not create:
            raise FileNotFoundError(path)

        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        # NORMAL is safe under WAL: a crash cannot corrupt the database, it can
        # only lose the last commit or two. Worth it here because the looper
        # commits once per changed player.
        conn.execute("PRAGMA synchronous = NORMAL")

        if fresh:
            with open(schema_path, "r", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (1, ?)",
                (utcnow(),))

        _conn, _path = conn, path
        return _conn


def conn():
    if _conn is None:
        return connect()
    return _conn


def close():
    global _conn, _path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, _path = None, None


def path():
    return _path


@contextmanager
def transaction():
    """Group writes so they land together or not at all.

    This is what keeps a _current row and its _history row from ever
    disagreeing, and it is also the fix for a real bug in the JSON version:
    LoopPlayerHandler.remove_cache() wrote the whole runescape file once at the
    end of a loop, so a process killed mid-loop had already posted to Discord
    but never recorded it, and the next loop re-posted the same milestones.

    Reentrant — a nested `with transaction()` joins the outer one rather than
    starting a second.
    """
    connection = conn()
    with _lock:
        if connection.in_transaction:
            yield connection
            return
        connection.execute("BEGIN")
        try:
            yield connection
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")


def query(sql, params=()):
    return conn().execute(sql, params).fetchall()


def one(sql, params=()):
    return conn().execute(sql, params).fetchone()


def scalar(sql, params=(), default=None):
    row = one(sql, params)
    return default if row is None else row[0]


def execute(sql, params=()):
    return conn().execute(sql, params)


def executemany(sql, rows):
    return conn().executemany(sql, rows)

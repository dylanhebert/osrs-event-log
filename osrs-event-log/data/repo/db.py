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
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join("data", "osrs.db")
DEFAULT_SCHEMA_PATH = os.path.join("data", "schema.sql")

_conn = None
_path = None
_lock = threading.RLock()

# Read-only mode only. When set, conn() hands out a connection PER THREAD
# instead of one shared object. See connect_readonly() for why.
_ro_path = None
_ro_local = threading.local()


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


def connect_readonly(path):
    """Open an existing database for reading only. For the web UI, not the bot.

    Additive: nothing in the bot calls this, and no existing function changed to
    accommodate it. It sets the same module-level connection the rest of this
    package reads through, so every repo read function works unmodified in a
    process that opened the database this way.

    Three differences from connect(), each of which is load-bearing:

      * `mode=ro` in the URI. A write attempt fails instead of succeeding.
      * `PRAGMA query_only = ON`, so even a mistake inside a read path cannot
        write. Belt and braces, cheap.
      * NO `PRAGMA journal_mode = WAL`. Setting journal_mode writes the database
        header, which is exactly what a reader must not do. WAL is already on,
        set by the bot, and it is a persistent property of the file.

    It also refuses to create anything. connect() creates the database from
    schema.sql when the file is missing, which in a read-only service would
    silently produce an empty database and a site that renders as though every
    player vanished. Here a wrong path is an immediate FileNotFoundError.

    ONE CONNECTION PER THREAD. The bot is a single process with a single event
    loop, so it shares one connection safely. A web server is not: anything that
    serves requests on threads will have several of them in this module at once,
    and a shared sqlite3 connection then interleaves cursors between them. That
    is not theoretical. It produced, from a threaded dev server:

        sqlite3.InterfaceError: bad parameter or other API misuse
        ValueError: list.index(x): x not in list   <- one request reading
                                                     another request's rows

    Handing each thread its own connection removes the whole class of problem
    and costs nothing: a SQLite connection is a file handle and some memory, and
    a read-only one cannot conflict with any other.

    WAL CAVEAT, and it will bite one day: a read-only connection to a WAL
    database still needs WRITE permission on the `-shm` lock file, or on the
    directory if `-shm` does not exist yet. `mode=ro` restricts the database
    file, not the locking machinery. Bot and UI run as the same user today, so
    this works; the day the UI runs as its own user, reads start failing with
    "unable to open database file". The fix is file permissions, NOT
    `immutable=1` — the bot is actively writing, and immutable would hand the UI
    a stale, torn view.
    """
    global _conn, _path, _ro_path
    with _lock:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path}: no such database. The web UI never creates one — "
                "check the configured database path.")
        if _conn is not None:
            _conn.close()
            _conn, _path = None, None

        _ro_path = path
        _path = path
        # Open one for this thread now, so a bad path fails at startup rather
        # than on whichever request happens to arrive first.
        _conn = _open_readonly(path)
        _ro_local.conn = _conn
        return _conn


def _open_readonly(path):
    uri = "file:" + pathlib.PurePath(path).as_posix() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False,
                                 isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def conn():
    # Read-only mode gives each thread its own connection. The bot never takes
    # this branch: nothing sets _ro_path unless connect_readonly() was called.
    if _ro_path is not None:
        connection = getattr(_ro_local, "conn", None)
        if connection is None:
            connection = _open_readonly(_ro_path)
            _ro_local.conn = connection
        return connection
    if _conn is None:
        return connect()
    return _conn


def close():
    global _conn, _path, _ro_path
    with _lock:
        if _conn is not None:
            _conn.close()
        # Only this thread's read-only connection can be closed from here;
        # others are released when their thread ends.
        other = getattr(_ro_local, "conn", None)
        if other is not None and other is not _conn:
            other.close()
        _ro_local.conn = None
        _conn, _path, _ro_path = None, None, None


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

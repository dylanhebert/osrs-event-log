"""The UI's one connection to the bot's database, opened read-only.

Everything funnels through repo.db.connect_readonly(), which opens with
`mode=ro` and `PRAGMA query_only = ON` and refuses to create anything. See the
long comment on that function for why journal_mode is deliberately not set and
for the WAL/-shm permission caveat.

The connection is per process. Gunicorn runs SYNC workers (see the systemd unit
in docs/web-ui.md), so each worker is a separate process with its own
connection and there is no cross-thread sharing. Do not switch to gthread
without giving this module a thread-local connection first: repo.db keeps one
module-global sqlite3 connection, and interleaving cursors across threads on a
shared connection is a real bug, not a theoretical one.
"""

from . import config  # noqa: F401  (puts the bot's package on sys.path)

from data import repo  # noqa: E402


_opened_path = None


def open_readonly(db_path):
    """Open the database for this process. Called once at app creation."""
    global _opened_path
    repo.db.connect_readonly(db_path)
    _opened_path = db_path
    return repo.db.conn()


def path():
    return _opened_path


def assert_read_only():
    """Prove the connection cannot write. Runs at startup, costs microseconds.

    Worth doing rather than trusting the flags: a read-only service that is
    quietly writable is exactly the kind of thing nobody notices until it has
    already corrupted something the bot cared about. Failing to start is the
    correct response.
    """
    import sqlite3
    try:
        repo.db.conn().execute(
            "CREATE TABLE _readonly_probe (x INTEGER)")
    except sqlite3.OperationalError:
        return True
    # The statement succeeded, so the connection is writable. Undo it and refuse
    # to start.
    try:
        repo.db.conn().execute("DROP TABLE _readonly_probe")
    except sqlite3.Error:
        pass
    raise RuntimeError(
        "The database opened WRITABLE. The web UI must never be able to write "
        "to the bot's database. Refusing to start.")

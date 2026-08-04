"""Data access for osrs-event-log.

Plain functions over SQLite, taking ids and strings. Nothing in this package
imports discord.py, aiohttp, or the bot's config, which means:

  * the test harness can exercise it with no bot token and no network
  * a future read-only web UI (Flask on :8007) can `from data.repo import ...`
    without pulling in the bot

data/handlers/ sits on top as a thin adapter layer, keeping the signatures the
cogs already call (which take discord.py Server/Member objects). Cogs are
unchanged by the SQLite migration.

    from data import repo
    repo.connect()
    stats = repo.stats.load_all_pollable()
"""

from . import (competitions, db, events, members, players, servers, stats,
               webauth)
from .db import close, connect, connect_readonly, transaction, utcnow

__all__ = [
    "competitions", "db", "events", "members", "players", "servers", "stats",
    "webauth",
    "connect", "close", "connect_readonly", "transaction", "utcnow", "bootstrap",
]


def bootstrap(path=None, schema_path=None):
    """Open the database, creating it from schema.sql if it does not exist.

    Replaces handlers.verify_files(), which created empty JSON files on first
    run. Returns the connection.
    """
    connection = connect(path=path, schema_path=schema_path)
    stats.reset_caches()
    return connection

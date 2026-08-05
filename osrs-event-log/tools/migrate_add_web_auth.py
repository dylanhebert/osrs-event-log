"""Bring an existing database up to schema version 3, for the web UI.

data/schema.sql is only ever executed when a database is created from nothing,
so changing it does not reach a database that already exists. This script is the
other half.

    v2  web_credentials       sign-in credentials, hash only
    v3  servers.name          guild display name, so the UI can label a server
        servers.icon_hash     guild icon, so it can show one
    v4  discord_members       who owns an account: name and avatar hash
    v5  events.discord_message_id  so a Discord backfill can re-run safely
    v6  events.is_milestone       did this event ping the role

It is idempotent and additive: it creates tables, an index and nullable columns,
rewrites no existing row, and drops nothing. Safe to run more than once and safe
to run while the bot is up, though the deploy window is tidier. See
docs/web-ui.md.

    python tools/migrate_add_web_auth.py --report          # writes nothing
    python tools/migrate_add_web_auth.py --db data/osrs.db
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 6

NEW_TABLES = ["web_credentials", "discord_members"]

DDL = [
    """
    CREATE TABLE IF NOT EXISTS web_credentials (
        member_id     INTEGER PRIMARY KEY,
        token_hash    TEXT    NOT NULL,
        issued_at     TEXT    NOT NULL,
        issued_count  INTEGER NOT NULL DEFAULT 1
    ) WITHOUT ROWID
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_web_credentials_hash
        ON web_credentials(token_hash)
    """,
    """
    CREATE TABLE IF NOT EXISTS discord_members (
        member_id     INTEGER PRIMARY KEY,
        username      TEXT,
        display_name  TEXT,
        avatar_hash   TEXT,
        updated_at    TEXT NOT NULL
    ) WITHOUT ROWID
    """,
]

# SQLite has no ADD COLUMN IF NOT EXISTS, so these are guarded by inspecting
# PRAGMA table_info instead. Both are nullable with no default, which is what
# makes adding them to a live table instant and non-rewriting.
NEW_COLUMNS = [
    ("servers", "name", "TEXT"),
    ("servers", "icon_hash", "TEXT"),
    ("events", "discord_message_id", "INTEGER"),
    ("events", "is_milestone", "INTEGER NOT NULL DEFAULT 0"),
]

# Partial indexes on the new columns, created after the columns exist.
LATE_DDL = [
    """
    CREATE INDEX IF NOT EXISTS idx_events_discord_msg
        ON events(discord_message_id) WHERE discord_message_id IS NOT NULL
    """,
]


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_version(conn):
    row = conn.execute(
        "SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if row and row[0] is not None else 0


def table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone() is not None


def column_exists(conn, table, column):
    return any(row[1] == column
               for row in conn.execute(f"PRAGMA table_info({table})"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.path.join("data", "osrs.db"))
    parser.add_argument("--report", action="store_true",
                        help="say what would happen and write nothing")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        # Deliberately not creating one. A missing database here means the path
        # is wrong, and creating an empty one is how a bot comes up with zero
        # players and starts rebuilding state on top of live data.
        print(f"ERROR: {args.db} does not exist. This script migrates an "
              f"existing database; it does not create one.", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        version = current_version(conn)
        missing_tables = [t for t in NEW_TABLES if not table_exists(conn, t)]
        missing_columns = [(t, c, d) for t, c, d in NEW_COLUMNS
                           if not column_exists(conn, t, c)]

        print(f"database        {args.db}")
        print(f"schema_version  {version}")
        for table in NEW_TABLES:
            print(f"{table:<23} {'MISSING' if table in missing_tables else 'present'}")
        for table, column, _ in NEW_COLUMNS:
            present = not any(c == column for _, c, _ in missing_columns)
            print(f"{table + '.' + column:<23} {'present' if present else 'MISSING'}")

        todo = missing_tables or missing_columns or version < SCHEMA_VERSION
        if not todo:
            print(f"\nNothing to do: already at version {SCHEMA_VERSION}.")
            return 0

        if args.report:
            print("\n--report, would apply:")
            for table in missing_tables:
                print(f"  CREATE TABLE {table}")
            for table, column, decl in missing_columns:
                print(f"  ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if version < SCHEMA_VERSION:
                print(f"  record schema_version {SCHEMA_VERSION}")
            print("Nothing written.")
            return 0

        with conn:
            for statement in DDL:
                conn.execute(statement)
            for table, column, decl in missing_columns:
                # Nullable with no default, so SQLite records this in the
                # header without rewriting a single row.
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            # After the columns exist, not before.
            for statement in LATE_DDL:
                conn.execute(statement)
            # Existing hiscores rows already record this in event_type, so
            # backfilling the flag from them is exact rather than a guess.
            # Dink rows cannot be recovered this way and stay 0 until a
            # Discord sweep re-reads them.
            if "is_milestone" in {c for _, c, _ in missing_columns}:
                conn.execute(
                    "UPDATE events SET is_milestone = 1"
                    " WHERE source = 'hiscores' AND event_type = 'MILESTONE'")
            if version < SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utcnow()))

        print(f"\nOK: schema_version {SCHEMA_VERSION}.")
        print(f"     web_credentials rows: "
              f"{conn.execute('SELECT COUNT(*) FROM web_credentials').fetchone()[0]}")

        named = conn.execute(
            "SELECT COUNT(*) FROM servers WHERE name IS NOT NULL").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
        print(f"     servers with a name: {named} of {total}")

        known = conn.execute("SELECT COUNT(*) FROM discord_members").fetchone()[0]
        linked = conn.execute(
            "SELECT COUNT(DISTINCT ps.member_id) FROM player_servers ps"
            " JOIN servers s ON s.id = ps.server_id"
            " WHERE s.is_active = 1 AND ps.member_id IS NOT NULL").fetchone()[0]
        print(f"     members known:       {known} of {linked} linked")

        if named < total or known < linked:
            print("\n     The bot fills these in on its next start. Until then"
                  " the UI shows ordinals\n     and monograms, which is the"
                  " designed degraded state, not a failure.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

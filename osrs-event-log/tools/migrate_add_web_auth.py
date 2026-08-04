"""Add the web_credentials table to an existing database. Schema version 2.

data/schema.sql is only ever executed when a database is created from nothing,
so adding a table there does not reach a database that already exists. This
script is the other half: it brings a live database up to match the schema file.

It is idempotent and additive. It creates one table and one index, touches no
existing table, and rewrites no existing row, so it is safe to run against the
production database more than once and safe to run while the bot is up. Running
it during the deploy window anyway is tidier: see docs/web-ui.md.

    python tools/migrate_add_web_auth.py --report          # writes nothing
    python tools/migrate_add_web_auth.py --db data/osrs.db
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 2

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
        already = table_exists(conn, "web_credentials")
        version = current_version(conn)
        print(f"database        {args.db}")
        print(f"schema_version  {version}")
        print(f"web_credentials {'present' if already else 'MISSING'}")

        if already and version >= SCHEMA_VERSION:
            print("\nNothing to do: already at version 2.")
            return 0

        if args.report:
            print(f"\n--report: would create web_credentials + its unique index"
                  f" and record schema_version {SCHEMA_VERSION}. Nothing written.")
            return 0

        with conn:
            for statement in DDL:
                conn.execute(statement)
            if version < SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utcnow()))

        print(f"\nOK: web_credentials ready, schema_version {SCHEMA_VERSION}.")
        print(f"     rows: {conn.execute('SELECT COUNT(*) FROM web_credentials').fetchone()[0]}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""players.last_polled must track fetches, not writes.

    python tools/test_last_polled.py

Found in production after the cutover. last_polled was only being set by
stats.apply_changes(), which runs when something actually changed — so after two
full poll cycles only 3 of 70 players had it set, and those three only because
they have no Overall row and therefore always take the write path.

That makes the column mean "last written", which for a UI is actively
misleading: it cannot distinguish "this player has not trained since Tuesday"
from "we have not been able to reach this account since Tuesday". The looper now
calls mark_polled() as soon as a fetch parses, before the unchanged early-out.

Offline: no Discord, no network, scratch database.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    scratch = tempfile.mkdtemp(prefix="osrs-polled-")
    db_path = os.path.join(scratch, "osrs.db")
    fails = []

    try:
        result = subprocess.run(
            [sys.executable, os.path.join(here, "migrate_json_to_sqlite.py"),
             "--data-dir", args.data_dir,
             "--schema", os.path.join("data", "schema.sql"),
             "--db", db_path],
            capture_output=True, text=True)
        if result.returncode:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode

        from data import repo
        from data.handlers.LoopPlayerHandler import LoopPlayerHandler
        from tools import harness

        harness.quiet_logging()
        repo.connect(path=db_path)
        handler = LoopPlayerHandler()

        player = sorted(repo.stats.load_all_pollable())[0]
        player_id = repo.players.get_id(player)

        def polled_at(pid):
            return repo.db.scalar("SELECT last_polled FROM players WHERE id = ?", (pid,))

        # The migration should not claim anyone has been polled.
        if polled_at(player_id) is not None:
            fails.append("migration set last_polled; it should start NULL")

        # A fetch that changed nothing must still count as a poll. This is the
        # case that was broken: it is the overwhelming majority of players.
        asyncio.run(handler.mark_polled(player))
        first = polled_at(player_id)
        if first is None:
            fails.append("mark_polled did not set last_polled")

        # ...and it must not have written any stats or history to do it.
        history = repo.db.scalar(
            "SELECT COUNT(*) FROM player_skill_history WHERE player_id = ?"
            " AND recorded_at > ?", (player_id, first or ""), 0)
        if history:
            fails.append(f"mark_polled wrote {history} history rows; it must write none")

        # An unknown player is a no-op, not a crash — a rename mid-cycle should
        # not take the loop down.
        try:
            asyncio.run(handler.mark_polled("No+Such+Player+Here"))
        except Exception as exc:
            fails.append(f"mark_polled raised on an unknown player: {exc!r}")

        # Never the reason a cycle dies.
        repo.db.execute("ALTER TABLE players RENAME TO players_hidden")
        try:
            asyncio.run(handler.mark_polled(player))
        except Exception as exc:
            fails.append(f"mark_polled raised on a broken database: {exc!r}")
        repo.db.execute("ALTER TABLE players_hidden RENAME TO players")

        repo.close()

        print("\n" + "=" * 68)
        if fails:
            print(f"  LAST_POLLED: FAILED — {len(fails)} problem(s)")
            print("=" * 68 + "\n")
            for problem in fails:
                print(f"    {problem}")
            return 1

        print("  LAST_POLLED: PASSED")
        print("=" * 68 + "\n")
        print("    starts NULL, set by a fetch that changed nothing,")
        print("    writes no stats or history, and survives an unknown")
        print("    player and a broken database without raising.\n")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

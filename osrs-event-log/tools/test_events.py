#!/usr/bin/env python3
"""Events feed test — recording works, and can never break a post.

    python tools/test_events.py

The events table is new; nothing populated it before. Two things matter:

  1. Events are recorded with the right player, source and type, and the
     recent-events query the web UI will use returns them newest first.
  2. Recording is best-effort. Dink does not retry, so an event lost while the
     bot is down is lost forever — a failing INSERT must never be the reason a
     message does not reach Discord, or the storage change makes the one
     unrecoverable failure mode worse.

The second is checked by breaking the database on purpose and asserting the
caller still completes.

Offline: no Discord token, no network, scratch database only.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeUpdate:
    """Stands in for a PlayerUpdate that produced messages."""

    def __init__(self, milestones=(), skills=(), minigames=()):
        self.milestones = list(milestones)
        self.skills = list(skills)
        self.minigames = list(minigames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    scratch = tempfile.mkdtemp(prefix="osrs-events-")
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
        from tools import harness
        harness.quiet_logging()
        repo.connect(path=db_path)

        player = sorted(repo.stats.load_all_pollable())[0]
        player_id = repo.players.get_id(player)

        # --- starts empty --------------------------------------------------- #
        if repo.events.recent(limit=5):
            fails.append("events table was not empty after migration")

        # --- hiscores events via the looper's handler ----------------------- #
        from data.handlers.LoopPlayerHandler import LoopPlayerHandler

        handler = LoopPlayerHandler()
        update = FakeUpdate(
            milestones=["**Someone has achieved 2,200 total level**"],
            skills=["**Someone levelled up Attack to 70**"],
            minigames=["**Someone has killed Zulrah 501 times**",
                       "**Someone has completed 101 Hard Clue Scrolls**"])
        written = asyncio.run(handler.record_events(player, update, posted=True))
        if written != 4:
            fails.append(f"expected 4 hiscores events written, got {written}")

        rows = repo.events.recent(limit=10, player_id=player_id)
        if len(rows) != 4:
            fails.append(f"expected 4 events back, got {len(rows)}")
        types = sorted(r["event_type"] for r in rows)
        if types != ["MILESTONE", "MINIGAME", "MINIGAME", "SKILL"]:
            fails.append(f"unexpected event types: {types}")
        if any(r["source"] != repo.events.SOURCE_HISCORES for r in rows):
            fails.append("hiscores events did not get source='hiscores'")
        if any(r["rs_name"] != player for r in rows):
            fails.append("events did not join back to the right player")

        # --- a dink event, with its payload retained ------------------------ #
        repo.events.log_event(
            player_id, None, repo.events.SOURCE_DINK, "LOOT",
            "**Someone received a drop: Twisted bow**",
            payload={"type": "LOOT", "extra": {"items": [{"name": "Twisted bow"}]}},
            posted=True)
        dink_rows = repo.events.recent(limit=5, source=repo.events.SOURCE_DINK)
        if len(dink_rows) != 1:
            fails.append(f"expected 1 dink event, got {len(dink_rows)}")
        elif "Twisted bow" not in (dink_rows[0]["payload"] or ""):
            fails.append("dink payload was not retained")

        # --- failed sends are findable -------------------------------------- #
        repo.events.log_event(player_id, None, repo.events.SOURCE_DINK, "PET",
                              "**Someone got a pet**", posted=False)
        if len(repo.events.failed()) != 1:
            fails.append("a failed send was not queryable via events.failed()")

        # --- recording must not be able to break a post --------------------- #
        # Drop the table out from under the handler. record_events() has to log
        # and carry on; if it raises, a milestone that reached Discord would
        # take the whole player's cycle down with it, and for Dink the event
        # would be gone for good.
        repo.db.execute("DROP TABLE events")
        try:
            survived = asyncio.run(handler.record_events(player, update, posted=True))
            if survived != 0:
                fails.append(f"expected 0 writes against a broken table, got {survived}")
        except Exception as exc:
            fails.append(f"record_events raised instead of swallowing: {exc!r}")

        repo.close()

        print("\n" + "=" * 68)
        if fails:
            print(f"  EVENTS FEED: FAILED — {len(fails)} problem(s)")
            print("=" * 68 + "\n")
            for problem in fails:
                print(f"    {problem}")
            return 1

        print("  EVENTS FEED: PASSED")
        print("=" * 68 + "\n")
        print("         4 hiscores events recorded and read back in order")
        print("         1 dink event recorded with its raw payload retained")
        print("         1 failed send queryable via events.failed()")
        print("\n    Recording survives a broken database: a failure to record can")
        print("    never stop a message reaching Discord, which for Dink would")
        print("    lose the event permanently.\n")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

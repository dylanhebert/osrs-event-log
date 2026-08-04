#!/usr/bin/env python3
"""One side of the T3 golden diff. Not run directly — see test_golden_diff.py.

Runs a fixed list of hiscores payloads through whichever version of the update
code lives in the tree it is invoked from, and dumps the messages that would
have been posted. test_golden_diff.py runs it twice — once in a pristine
pre-migration checkout with --mode json, once in the working tree with
--mode sqlite — and diffs the two outputs.

Both sides must be given byte-identical payloads. The only thing that may differ
between the runs is how the *stored* state is represented: comma-formatted
strings in the JSON tree, integers in the SQLite tree. Any difference in the
resulting messages is therefore caused by the migration, which is the whole
point of the exercise.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_bases_json(players):
    """Pre-migration stored state: comma-formatted strings, '--' for unranked."""
    with open(os.path.join("data", "db_runescape.json"), "r", encoding="utf-8") as fh:
        everything = json.load(fh)
    return {name: everything[name] for name in players}


def load_bases_sqlite(players, db_path):
    """Migrated stored state: integers, None for unranked."""
    from data import repo
    repo.connect(path=db_path)
    out = {name: repo.stats.get_player_stats(repo.players.get_id(name))
           for name in players}
    repo.close()
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("json", "sqlite"), required=True)
    parser.add_argument("--payloads", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", default=None, help="required for --mode sqlite")
    args = parser.parse_args(argv)

    from tools import harness
    harness.quiet_logging()

    with open(args.payloads, "r", encoding="utf-8") as fh:
        cases = json.load(fh)

    players = sorted({player for player, _, _ in cases})
    bases = (load_bases_json(players) if args.mode == "json"
             else load_bases_sqlite(players, args.db))

    results = {}
    with harness.dry_run() as sotw_calls:
        for player, label, payload in cases:
            captured = asyncio.run(
                harness.run_player(player, bases[player], payload, mutate=False))
            results[f"{player}::{label}"] = {
                "skipped": captured.skipped,
                "error": captured.error,
                "milestones": captured.milestones,
                "skills": captured.skills,
                "minigames": captured.minigames,
            }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"mode": args.mode, "players": players,
                   "results": results, "sotw_calls": sotw_calls},
                  fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

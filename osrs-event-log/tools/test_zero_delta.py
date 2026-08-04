#!/usr/bin/env python3
"""T2 — zero-delta test. The migration must not make anything look changed.

    python tools/test_zero_delta.py
    python tools/test_zero_delta.py --data-dir fixtures/live-2026-08-04

Migrates the JSON into a scratch database, then reconstructs an
index_lite.json payload from the database's OWN contents and runs the update
logic over it. Nothing has changed in the game, so every player must report
"overall xp unchanged" and produce zero messages.

This is the direct test of the failure the whole project is built around: if the
stored form and the parsed form disagree by so much as a formatting detail,
every skill of every player compares as changed and the bot posts a milestone
for all of them, in every server, with no rate limit and no undo.

Fully offline and deterministic — no Discord token, no network, no calls to
Jagex. Nothing is written to the source data directory.

A pass here means the migration is spam-safe. It does NOT mean messages are
unchanged in content — that is T3 (test_golden_diff.py), which is the test that
catches milestones silently disappearing.
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
    parser.add_argument("--verbose", action="store_true",
                        help="print every message any player would have posted")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    scratch = tempfile.mkdtemp(prefix="osrs-zerodelta-")
    db_path = os.path.join(scratch, "osrs.db")

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
        players = repo.stats.load_all_pollable()

        hiscores = harness.FakeHiscores()
        for rs_name, stats in players.items():
            hiscores.add(rs_name, harness.FakeHiscores.payload_from_stats(stats))

        with harness.dry_run() as sotw_calls:
            results = asyncio.run(harness.run_all(players, hiscores, mutate=False))

        repo.close()

        summary = harness.summarise(results)
        offenders = {name: r for name, r in results.items() if r.changed or r.error}

        print("\n" + "=" * 68)
        if offenders or sotw_calls:
            print(f"  T2 ZERO-DELTA: FAILED")
            print("=" * 68 + "\n")
            print(f"    {len(offenders)} of {summary['players']} players reported a change "
                  "against their own stored data.\n")
            print("    The stored form and the parsed form disagree. Running the bot")
            print("    in this state would post a milestone for every one of these.\n")
            for name, captured in list(offenders.items())[:10]:
                print(f"    {name}: {captured!r}")
                if captured.error:
                    print(f"        error: {captured.error}")
                for message in captured.messages[:3]:
                    print(f"        {message[:150]}")
            if len(offenders) > 10:
                print(f"\n    ... and {len(offenders) - 10} more")
            if sotw_calls:
                print(f"\n    {len(sotw_calls)} SOTW/BOTW accumulator writes were attempted "
                      "(expected 0)")
            return 1

        print("  T2 ZERO-DELTA: PASSED")
        print("=" * 68 + "\n")
        print(f"    {summary['players']:>6,} players replayed against their own stored data")
        print(f"    {summary['unchanged']:>6,} skipped on the Overall early-out")
        print(f"    {summary['walked_no_change']:>6,} walked every skill, nothing differed "
              "(no Overall row)")
        print(f"    {summary['no_profile']:>6,} have no hiscores profile stored")
        print(f"    {summary['changed']:>6,} reported a change   <- must be 0")
        print(f"    {summary['errors']:>6,} errors              <- must be 0")
        print(f"    {summary['messages']:>6,} messages would be posted   <- must be 0")
        print("\n    The migration cannot cause a spam event: every stored value")
        print("    parses back to exactly what change detection compares against.\n")

        if args.verbose:
            for name, captured in results.items():
                print(f"    {name}: {captured.skipped}")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

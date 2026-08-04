#!/usr/bin/env python3
"""T5 — live read-only run. The last check before cutting over.

    python tools/test_live_readonly.py --data-dir ../fixtures/live-YYYY-MM-DD
    python tools/test_live_readonly.py --limit 10        # smaller sample

THIS ONE HITS THE NETWORK. Every other test is offline; this fetches real
hiscores from Jagex for each pollable player and runs the real comparison
against real migrated state.

It still posts nothing and writes nothing: no Discord connection is made, the
database is a scratch copy, and the SOTW/BOTW accumulator is stubbed out.

What it is for: T1-T3 prove the migration is faithful and the messages are
unchanged, but they all replay stored or synthetic data. This is the only check
that exercises fetch -> parse -> compare end to end against what the hiscores
actually return today, which is where a parser assumption would show up.

The healthy shape, from the 2026-08-04 baseline:

    ~53 players skipped ("Overall xp unchanged")
     ~5 players with real updates
    ~12 fetch failures / not on the hiscores
      0 crashes

The tripwire is the ratio, not the count. If most successfully-fetched players
report changes, the formatting contract is broken and the bot is about to post a
milestone for every skill of every player in every server. That fails the run.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Same concurrency the looper uses in production (PLAYER_THREAD_LIMIT).
DEFAULT_CONCURRENCY = 5

# Above this share of fetched players reporting changes, assume the formatting
# contract is broken rather than that everyone trained at once.
SPAM_RATIO = 0.5


async def fetch_all(players, concurrency, progress=True):
    import common.util as util

    semaphore = asyncio.Semaphore(concurrency)
    payloads = {}
    done = 0

    async def one(rs_name):
        nonlocal done
        async with semaphore:
            payloads[rs_name] = await util.get_page(rs_name)
            done += 1
            if progress and done % 10 == 0:
                print(f"    fetched {done}/{len(players)}...", flush=True)

    await asyncio.gather(*(one(name) for name in players))
    return payloads


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--limit", type=int, default=None,
                        help="only check the first N players")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--show", type=int, default=8,
                        help="how many changed players to print in full")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    scratch = tempfile.mkdtemp(prefix="osrs-live-")
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
        repo.close()

        names = sorted(players)
        if args.limit:
            names = names[:args.limit]
        players = {name: players[name] for name in names}

        print(f"\n  Fetching live hiscores for {len(players)} players "
              f"({args.concurrency} at a time). Nothing is posted or written.\n")
        payloads = asyncio.run(fetch_all(players, args.concurrency))

        hiscores = harness.FakeHiscores(payloads)
        with harness.dry_run() as sotw_calls:
            results = asyncio.run(harness.run_all(players, hiscores, mutate=False))

        summary = harness.summarise(results)
        fetched = summary["players"] - summary["fetch_failed"]
        changed = summary["changed"]
        ratio = (changed / fetched) if fetched else 0.0

        print("\n" + "=" * 68)
        print("  T5 LIVE READ-ONLY")
        print("=" * 68 + "\n")
        print(f"    {summary['players']:>6,} players polled")
        print(f"    {summary['unchanged']:>6,} skipped, Overall xp unchanged")
        print(f"    {summary['walked_no_change']:>6,} walked every skill, nothing differed")
        print(f"    {summary['fetch_failed']:>6,} fetch failed (404, timeout, not on hiscores)")
        print(f"    {summary['no_profile']:>6,} returned no hiscores profile")
        print(f"    {changed:>6,} with real updates")
        print(f"    {summary['errors']:>6,} errors")
        print(f"    {summary['messages']:>6,} messages would have been posted")
        print(f"\n    changed / fetched = {changed}/{fetched} = {ratio:.0%}")

        changers = [(n, r) for n, r in results.items() if r.changed]
        if changers:
            print(f"\n  What would have been posted "
                  f"(showing {min(len(changers), args.show)} of {len(changers)}):\n")
            for name, captured in changers[:args.show]:
                print(f"    --- {name}")
                for message in captured.messages:
                    print(f"        {message[:160]}")

        errored = [(n, r) for n, r in results.items() if r.error]
        if errored:
            print("\n  Errors:\n")
            for name, captured in errored[:10]:
                print(f"    {name}: {captured.error}")

        if sotw_calls:
            print(f"\n  SOTW/BOTW accumulator calls intercepted: {len(sotw_calls)} "
                  "(stubbed, nothing written)")

        print()
        if summary["errors"]:
            print("  RESULT: FAILED — the update path raised on live data.\n")
            return 1
        if fetched and ratio > SPAM_RATIO:
            print(f"  RESULT: FAILED — {ratio:.0%} of fetched players report changes.")
            print("  That is the spam signature, not a busy week. Do not deploy;")
            print("  the stored form and the parsed form disagree.\n")
            return 1

        print("  RESULT: PASSED — the change rate looks like normal play.")
        print("  Read the messages above and sanity-check them before cutting over.\n")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

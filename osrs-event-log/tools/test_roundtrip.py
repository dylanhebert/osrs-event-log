#!/usr/bin/env python3
"""T1 — round-trip test. JSON -> SQLite -> JSON must reproduce the input.

    python tools/test_roundtrip.py
    python tools/test_roundtrip.py --data-dir fixtures/live-2026-08-04

Proves two things at once:

  * The migration loses nothing. Every key, every value, every player comes
    back. This is the reversibility requirement — if this passes, the rollback
    path (export back to JSON, redeploy the old code) is known to work.
  * parse_hiscore_value() and hiscore_value() are exact inverses over the real
    data. That is the formatting contract the whole spam risk hangs on: a
    stored "102,315,637" has to become 102315637 and come back identical.

Exits non-zero on any difference, printing the first 40.

Two normalisations are applied before comparing, both deliberate:

  * Lists that are used as sets are sorted on both sides. active_servers,
    all_players, all_servers, dinklinks and a member's player list are only ever
    iterated or membership-tested — never indexed — so their order carries no
    meaning. SOTW/BOTW history is NOT normalised: order matters there and is
    reproduced exactly through the seq column.
  * Top-level key order is ignored, since a dict is compared by content.

Nothing here writes into the source data directory.
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import migrate_json_to_sqlite as migrate          # noqa: E402
import export_sqlite_to_json as export            # noqa: E402

# Keys whose list value is order-insensitive. Everything else compares as-is.
UNORDERED_SUFFIXES = ("#all_players", "#all_servers", "#players")
UNORDERED_KEYS = {"active_servers", "removed_servers", "dinklinks"}


def normalise(db):
    out = {}
    for key, value in db.items():
        if key in UNORDERED_KEYS or key.endswith(UNORDERED_SUFFIXES):
            out[key] = sorted(value)
        else:
            out[key] = value
    return out


def diff(label, before, after, problems):
    before_keys, after_keys = set(before), set(after)
    for key in sorted(before_keys - after_keys):
        problems.append(f"{label}: key LOST -> {key!r}")
    for key in sorted(after_keys - before_keys):
        problems.append(f"{label}: key INVENTED -> {key!r}")
    for key in sorted(before_keys & after_keys):
        if before[key] != after[key]:
            problems.append(
                f"{label}: value CHANGED -> {key!r}\n"
                f"      before: {_short(before[key], key)}\n"
                f"      after : {_short(after[key], key)}")
    return problems


def _short(value, key=None):
    """Render a value for a diff line, redacting Dink link keys.

    Those are bearer tokens for the public webhook endpoint — anyone holding one
    can post events as any player. They must not end up in terminal scrollback,
    CI output or a pasted bug report just because a test failed.
    """
    if key is not None and ("dinklink" in key or key == "dinklinks"):
        if isinstance(value, list):
            return f"<{len(value)} dink keys redacted, {len(set(value))} distinct>"
        return "<dink key redacted>"
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 200 else text[:200] + " ..."


def compare_players(before, after, problems):
    """db_runescape.json, compared player by player so a mismatch names names."""
    for name in sorted(set(before) - set(after)):
        problems.append(f"runescape: player LOST -> {name}")
    for name in sorted(set(after) - set(before)):
        problems.append(f"runescape: player INVENTED -> {name}")
    for name in sorted(set(before) & set(after)):
        for section in ("skills", "minigames"):
            was, now = before[name].get(section, {}), after[name].get(section, {})
            for entry in sorted(set(was) - set(now)):
                problems.append(f"runescape: {name}.{section} LOST -> {entry}")
            for entry in sorted(set(now) - set(was)):
                problems.append(f"runescape: {name}.{section} INVENTED -> {entry}")
            for entry in sorted(set(was) & set(now)):
                if was[entry] != now[entry]:
                    problems.append(
                        f"runescape: {name}.{section}.{entry} CHANGED -> "
                        f"{was[entry]} != {now[entry]}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--keep", action="store_true",
                        help="keep the scratch directory and print its path")
    args = parser.parse_args(argv)

    schema_path = os.path.join(args.data_dir, "schema.sql")
    if not os.path.exists(schema_path):
        schema_path = os.path.join("data", "schema.sql")
    if not os.path.exists(schema_path):
        parser.error("cannot find schema.sql")

    scratch = tempfile.mkdtemp(prefix="osrs-roundtrip-")
    db_path = os.path.join(scratch, "osrs.db")
    out_dir = os.path.join(scratch, "out")

    try:
        print(f"  source     {os.path.abspath(args.data_dir)}")
        print(f"  scratch    {scratch}\n")

        rc = migrate.main([
            "--data-dir", args.data_dir,
            "--schema", schema_path,
            "--db", db_path,
        ])
        if rc != 0:
            print("  FAILED: migration returned non-zero", file=sys.stderr)
            return rc

        rc = export.main(["--db", db_path, "--out", out_dir])
        if rc != 0:
            print("  FAILED: export returned non-zero", file=sys.stderr)
            return rc

        problems = []

        def load(directory, *parts):
            with open(os.path.join(directory, *parts), "r", encoding="utf-8") as fh:
                return json.load(fh)

        diff("discord",
             normalise(load(args.data_dir, "db_discord.json")),
             normalise(load(out_dir, "db_discord.json")),
             problems)

        compare_players(load(args.data_dir, "db_runescape.json"),
                        load(out_dir, "db_runescape.json"),
                        problems)

        for label, parts in (("sotw_config", ("sotw", "sotw_config.json")),
                             ("botw_config", ("botw", "botw_config.json"))):
            before, after = load(args.data_dir, *parts), load(out_dir, *parts)
            if before != after:
                problems.append(f"{label}: CHANGED\n      before: {_short(before)}\n"
                                f"      after : {_short(after)}")

        print("\n" + "=" * 68)
        if problems:
            print(f"  T1 ROUND-TRIP: FAILED — {len(problems)} difference(s)")
            print("=" * 68 + "\n")
            for problem in problems[:40]:
                print(f"  {problem}")
            if len(problems) > 40:
                print(f"\n  ... and {len(problems) - 40} more")
            return 1

        source = load(args.data_dir, "db_discord.json")
        players = load(args.data_dir, "db_runescape.json")
        rows = sum(len(p.get("skills", {})) + len(p.get("minigames", {}))
                   for p in players.values())
        print("  T1 ROUND-TRIP: PASSED")
        print("=" * 68 + "\n")
        print(f"    {len(source):>6,} db_discord.json keys reproduced exactly")
        print(f"    {len(players):>6,} players reproduced exactly")
        print(f"    {rows:>6,} skill/minigame values survived int conversion "
              "and came back identical")
        print("\n    Reversibility confirmed: export_sqlite_to_json.py can rebuild"
              "\n    the JSON state if the migration has to be rolled back.\n")
        return 0
    finally:
        if args.keep:
            print(f"  kept {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

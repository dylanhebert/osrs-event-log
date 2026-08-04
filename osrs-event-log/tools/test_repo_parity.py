#!/usr/bin/env python3
"""Parity test — the repo layer must answer exactly what the JSON files said.

    python tools/test_repo_parity.py
    python tools/test_repo_parity.py --data-dir fixtures/live-2026-08-04

Migrates a copy of the JSON into a scratch database, then asks data/repo the
same questions the old handler code asked the JSON dicts, and asserts the
answers match. Runs offline with no bot token and no Discord connection.

This sits between T1 (nothing was lost writing it in) and T2/T3 (the looper
behaves identically reading it back out). It is the one that catches a repo
query that is subtly wrong — a missing COALESCE on a NULL opt-in, an ORDER BY
that changes who ranks third, an inactive server leaking into a link list.

The stat-value comparison is the important part: every stored "102,315,637"
must come back as the integer 102315637, and every '--' as None. That is the
formatting contract the entire spam risk rests on.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_value(raw):
    if raw in ("--", None):
        return None
    return int(str(raw).replace(",", ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    scratch = tempfile.mkdtemp(prefix="osrs-parity-")
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
        repo.connect(path=db_path)

        def load(*parts):
            with open(os.path.join(args.data_dir, *parts), "r", encoding="utf-8") as fh:
                return json.load(fh)

        discord_db = load("db_discord.json")
        runescape_db = load("db_runescape.json")
        active = set(discord_db["active_servers"])
        fails = []

        # --- what the looper iterates ------------------------------------- #
        loaded = repo.stats.load_all_pollable()
        expected = {name for name in runescape_db
                    if any(sid in active for sid in
                           discord_db.get(f"player:{name}#all_servers", []))}
        if set(loaded) != expected:
            fails.append(
                f"pollable set differs: only-json={sorted(expected - set(loaded))} "
                f"only-db={sorted(set(loaded) - expected)}")

        compared = 0
        for name in sorted(expected & set(loaded)):
            for section, fields in (("skills", ("rank", "level", "xp")),
                                    ("minigames", ("rank", "score"))):
                source, got = runescape_db[name][section], loaded[name][section]
                if set(source) != set(got):
                    fails.append(f"{name}.{section}: entry names differ")
                    continue
                for entry in source:
                    for field in fields:
                        want = parse_value(source[entry][field])
                        compared += 1
                        if want != got[entry][field]:
                            fails.append(
                                f"{name}.{section}.{entry}.{field}: "
                                f"json={source[entry][field]!r} -> {want} "
                                f"db={got[entry][field]!r}")

        # --- get_all_player_info equivalent -------------------------------- #
        for name in sorted(expected):
            want = [{"server": sid,
                     "member": discord_db[f"player:{name}#server:{sid}#member"],
                     "mention": discord_db[f"player:{name}#server:{sid}#mention"]}
                    for sid in sorted(discord_db[f"player:{name}#all_servers"])
                    if sid in active]
            got = repo.players.active_links(name)
            if want != got:
                fails.append(f"active_links({name}): want={want} got={got}")

        # --- server settings and membership -------------------------------- #
        for sid in sorted(active):
            want_members = {}
            for name in discord_db[f"server:{sid}#all_players"]:
                key = str(discord_db[f"player:{name}#server:{sid}#member"])
                want_members.setdefault(key, []).append(name)
            want_members = {k: sorted(v) for k, v in want_members.items()}
            got_members = {k: sorted(v)
                           for k, v in repo.servers.members_players(sid).items()}
            if want_members != got_members:
                fails.append(f"members_players({sid}) differs")

            want_info = {"id": sid,
                         "channel": discord_db[f"server:{sid}#channel"],
                         "role": discord_db[f"server:{sid}#role"]}
            if repo.servers.info(sid) != want_info:
                fails.append(f"servers.info({sid}) differs")

        # --- competitions --------------------------------------------------- #
        for kind in ("sotw", "botw"):
            score_key = "xp" if kind == "sotw" else "kills"
            player_col = "sotw_xp" if kind == "sotw" else "botw_kills"

            for sid in sorted(active):
                if repo.competitions.history(sid, kind) != \
                        discord_db[f"server:{sid}#{kind}_history"]:
                    fails.append(f"{kind} history({sid}) differs")

                want_top = sorted(
                    ({"player": name, score_key: discord_db[f"player:{name}#{player_col}"]}
                     for name in discord_db[f"server:{sid}#all_players"]
                     if discord_db[f"player:{name}#{player_col}"] > 0),
                    key=lambda d: (-d[score_key], d["player"]))[:10]
                got_top = repo.competitions.top_players(sid, kind)
                if want_top != got_top:
                    fails.append(f"{kind} top_players({sid}): want={want_top} got={got_top}")

            if repo.competitions.get_config(kind) != load(kind, f"{kind}_config.json"):
                fails.append(f"{kind} config differs")

        repo.close()

        print("\n" + "=" * 68)
        if fails:
            print(f"  REPO PARITY: FAILED — {len(fails)} difference(s)")
            print("=" * 68 + "\n")
            for problem in fails[:30]:
                print(f"  {problem}")
            if len(fails) > 30:
                print(f"\n  ... and {len(fails) - 30} more")
            return 1

        print("  REPO PARITY: PASSED")
        print("=" * 68 + "\n")
        print(f"    {compared:>6,} stat values match after int conversion")
        print(f"    {len(expected):>6,} players resolve to the same servers and members")
        print(f"    {len(active):>6,} servers match on settings, membership and standings")
        print("\n    SOTW and BOTW history and config reproduce exactly.\n")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

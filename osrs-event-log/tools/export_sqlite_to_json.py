#!/usr/bin/env python3
"""Rebuild the JSON state files from SQLite. The reverse of the migration.

    python tools/export_sqlite_to_json.py --db data/osrs.db --out /tmp/rollback

This is what makes the migration reversible. It is also half of the T1
round-trip test (tools/test_roundtrip.py), which migrates and exports and then
asserts the result matches the input.

Writes db_discord.json, db_runescape.json, sotw/sotw_config.json and
botw/botw_config.json into --out. It never writes into a live data directory
unless you point --out at one, and refuses to overwrite without --force.

Two things are deliberately not byte-preserved, because neither is meaningful:

  * List ORDER. active_servers, all_players, all_servers, dinklinks and a
    member's player list are all iterated or membership-tested, never indexed.
    They come back sorted. SOTW/BOTW history IS order-sensitive and is
    reproduced exactly, via the seq column.
  * Key ORDER within the JSON object. Same reason.

The round-trip test compares parsed structures with lists normalised, so both
of those are accounted for rather than ignored.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

JSON_DATE_FMT = "%m-%d-%y"


def hiscore_value(num):
    """Mirror of common/util.py hiscore_value(). Renders an integer the way the
    old scraped HTML page did, and an unranked entry as '--'."""
    if num is None:
        return "--"
    return "{:,}".format(num)


def _date_out(iso):
    """ISO back to the %m-%d-%y the JSON used. Anything the migration could not
    parse was stored verbatim and passes straight through."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime(JSON_DATE_FMT)
    except ValueError:
        return iso


def _bool_out(value):
    """NULL meant the JSON key was absent; the caller omits it entirely."""
    return None if value is None else bool(value)


def export_discord(conn):
    db = {}

    servers = conn.execute(
        "SELECT id, channel_id, role_id, sotw_opt, sotw_progress, botw_opt,"
        " botw_progress, is_active FROM servers ORDER BY id").fetchall()

    db["active_servers"] = sorted(r["id"] for r in servers if r["is_active"])
    db["removed_servers"] = sorted(r["id"] for r in servers if not r["is_active"])
    # DISTINCT: the list is a membership index for the webhook's validity check,
    # and live data has two accounts sharing one key. Without this the shared
    # key comes back twice and the round-trip fails.
    db["dinklinks"] = sorted(
        r["dink_link_key"] for r in conn.execute(
            "SELECT DISTINCT dink_link_key FROM players"
            " WHERE dink_link_key IS NOT NULL"))

    for row in servers:
        sid = row["id"]
        db[f"server:{sid}#channel"] = row["channel_id"]
        db[f"server:{sid}#role"] = row["role_id"]
        for field in ("sotw_opt", "sotw_progress", "botw_opt", "botw_progress"):
            value = _bool_out(row[field])
            if value is not None:
                db[f"server:{sid}#{field}"] = value

    # server -> all_players, and member -> players, both rebuilt from the links
    per_server = defaultdict(list)
    per_member = defaultdict(list)
    per_player = defaultdict(list)
    links = conn.execute(
        "SELECT p.rs_name, ps.server_id, ps.member_id, ps.mention, ps.sotw_opt,"
        " ps.botw_opt FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        " ORDER BY p.rs_name, ps.server_id").fetchall()

    for row in links:
        name, sid = row["rs_name"], row["server_id"]
        per_server[sid].append(name)
        per_player[name].append(sid)
        if row["member_id"] is not None:
            per_member[(row["member_id"], sid)].append(name)
        # Always emitted, unlike the bool fields. A NULL member_id means the key
        # was present with a null value — the "player was used here before and
        # is now open" case that check_player_member_link() handles. All 87
        # links carry the key today, so absence and null do not collide; if that
        # ever changes the round-trip test fails rather than silently inventing
        # the key.
        db[f"player:{name}#server:{sid}#member"] = row["member_id"]
        for field in ("mention", "sotw_opt", "botw_opt"):
            value = _bool_out(row[field])
            if value is not None:
                db[f"player:{name}#server:{sid}#{field}"] = value

    for row in servers:
        db[f"server:{row['id']}#all_players"] = sorted(per_server[row["id"]])
    for (mid, sid), names in per_member.items():
        db[f"member:{mid}#server:{sid}#players"] = sorted(names)

    for row in conn.execute(
            "SELECT rs_name, dink_link_key, sotw_xp, botw_kills FROM players"
            " ORDER BY rs_name"):
        name = row["rs_name"]
        # A player with no links had no all_servers key at all. remove_player()
        # deletes it when the list empties, so an empty list never persists.
        if per_player[name]:
            db[f"player:{name}#all_servers"] = sorted(per_player[name])
        db[f"player:{name}#sotw_xp"] = row["sotw_xp"]
        db[f"player:{name}#botw_kills"] = row["botw_kills"]
        if row["dink_link_key"] is not None:
            db[f"player:{name}#dinklink"] = row["dink_link_key"]

    # history
    for kind, week_tbl, wp_tbl, name_col, score_col in (
            ("sotw", "sotw_weeks", "sotw_week_players", "skill_name", "xp"),
            ("botw", "botw_weeks", "botw_week_players", "boss_name", "kills")):
        by_server = defaultdict(list)
        for week in conn.execute(
                f"SELECT id, server_id, {name_col} AS label, ended_on FROM {week_tbl}"
                " ORDER BY server_id, seq"):
            players = [
                {"player": p["player_name"],
                 score_col: p[score_col],
                 "rank": p["rank"]}
                for p in conn.execute(
                    f"SELECT player_name, {score_col}, rank FROM {wp_tbl}"
                    " WHERE week_id = ? ORDER BY seq", (week["id"],))
            ]
            by_server[week["server_id"]].append({
                "date": _date_out(week["ended_on"]),
                "skill" if kind == "sotw" else "boss": week["label"],
                "players": players,
            })
        for row in servers:
            db[f"server:{row['id']}#{kind}_history"] = by_server[row["id"]]

    # anything the migration parked, put back verbatim
    for row in conn.execute("SELECT key, value FROM legacy_kv ORDER BY key"):
        db[row["key"]] = json.loads(row["value"])

    return db


def export_runescape(conn):
    db = {}
    # tracked, not "has stat rows" — three players are tracked with empty dicts
    # and their entry has to come back or the round-trip loses them.
    for row in conn.execute(
            "SELECT id, rs_name FROM players WHERE tracked = 1 ORDER BY rs_name"):
        skills = {}
        for s in conn.execute(
                "SELECT sk.name, c.level, c.xp, c.rank FROM player_skill_current c"
                " JOIN skills sk ON sk.id = c.skill_id WHERE c.player_id = ?"
                " ORDER BY sk.sort_order IS NULL, sk.sort_order, sk.name", (row["id"],)):
            skills[s["name"]] = {
                "rank": hiscore_value(s["rank"]),
                "level": hiscore_value(s["level"]),
                "xp": hiscore_value(s["xp"]),
            }
        minigames = {}
        for a in conn.execute(
                "SELECT ac.name, c.score, c.rank FROM player_activity_current c"
                " JOIN activities ac ON ac.id = c.activity_id WHERE c.player_id = ?"
                " ORDER BY ac.sort_order", (row["id"],)):
            minigames[a["name"]] = {
                "rank": hiscore_value(a["rank"]),
                "score": hiscore_value(a["score"]),
            }
        db[row["rs_name"]] = {"skills": skills, "minigames": minigames}
    return db


def export_config(conn, key):
    row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default="data/osrs.db")
    parser.add_argument("--out", required=True,
                        help="directory to write the rebuilt JSON into")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files in --out")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        parser.error(f"no database at {args.db!r}")

    targets = {
        "db_discord.json": None,
        "db_runescape.json": None,
        os.path.join("sotw", "sotw_config.json"): None,
        os.path.join("botw", "botw_config.json"): None,
    }
    existing = [name for name in targets
                if os.path.exists(os.path.join(args.out, name))]
    if existing and not args.force:
        parser.error("refusing to overwrite without --force: "
                     + ", ".join(sorted(existing)))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        targets["db_discord.json"] = export_discord(conn)
        targets["db_runescape.json"] = export_runescape(conn)
        targets[os.path.join("sotw", "sotw_config.json")] = export_config(conn, "sotw_config")
        targets[os.path.join("botw", "botw_config.json")] = export_config(conn, "botw_config")
    finally:
        conn.close()

    for name, payload in targets.items():
        if payload is None:
            print(f"  skipped {name} (not in database)", file=sys.stderr)
            continue
        path = os.path.join(args.out, name)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            # indent=4, sort_keys=False matches helpers.db_write()
            json.dump(payload, handle, indent=4, sort_keys=False)
        print(f"  wrote {path} ({os.path.getsize(path):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Migrate osrs-event-log JSON state into SQLite. One-time, reversible.

Run from the inner osrs-event-log directory (the same cwd the bot needs):

    python tools/migrate_json_to_sqlite.py --report
    python tools/migrate_json_to_sqlite.py --db data/osrs.db

Reverse with tools/export_sqlite_to_json.py, which reproduces the input files.
tools/test_roundtrip.py runs both and diffs them.

This script imports nothing from the bot. common/util.py pulls in discord and
aiohttp and data/handlers/helpers.py reads bot_config.json at import time, so
depending on either would make the migration impossible to run without a token.
The two small functions that must agree with the bot are duplicated below and
marked; if they ever drift, test_roundtrip.py fails.

Nothing here writes to the JSON files. The source is opened read-only.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# db_discord.json keys that are known to be junk and may be dropped without
# aborting. Everything else unrecognised stops the migration. Keep this list
# short and justify each entry.
LEGACY_ALLOWLIST = {
    # sotw_xp is a global per-player counter; this server-scoped variant is a
    # leftover from an older layout and no code path reads it.
    re.compile(r"^player:[^#]+#server:\d+#sotw_xp$"),
}

# index_lite.json / hiscores display order. Anything not listed sorts last.
SKILL_ORDER = [
    "Overall", "Attack", "Defence", "Strength", "Hitpoints", "Ranged", "Prayer",
    "Magic", "Cooking", "Woodcutting", "Fletching", "Fishing", "Firemaking",
    "Crafting", "Smithing", "Mining", "Herblore", "Agility", "Thieving",
    "Slayer", "Farming", "Runecraft", "Hunter", "Construction", "Sailing",
]

JSON_DATE_FMT = "%m-%d-%y"


# --------------------------------------------------------------------------- #
# Duplicated from the bot — must stay in agreement
# --------------------------------------------------------------------------- #

def name_to_discord(name):
    """Mirror of common/util.py name_to_discord()."""
    if "+" in name:
        return name.title().replace("+", " ")
    return name.title()


def parse_hiscore_value(raw):
    """Reverse of common/util.py hiscore_value().

    The JSON stores what the old scraped HTML page rendered: thousands
    separators, and '--' for an unranked entry. Returns None for unranked.

    This is the single most important function in the migration. If it produces
    a different integer than the looper computes from index_lite.json, every
    skill of every player compares as changed on the first poll and the bot
    posts a milestone for all of them in every server.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        # index_lite uses -1 where the old page used '--'
        return None if raw == -1 else raw
    text = str(raw).strip()
    if text in ("--", "", "-"):
        return None
    return int(text.replace(",", ""))


# --------------------------------------------------------------------------- #
# Key patterns in db_discord.json
# --------------------------------------------------------------------------- #

RE_SERVER_FIELD = re.compile(
    r"^server:(?P<sid>\d+)#(?P<field>channel|role|sotw_opt|sotw_progress|botw_opt|botw_progress)$")
RE_SERVER_PLAYERS = re.compile(r"^server:(?P<sid>\d+)#all_players$")
RE_SERVER_HISTORY = re.compile(r"^server:(?P<sid>\d+)#(?P<kind>sotw|botw)_history$")
RE_PLAYER_SERVERS = re.compile(r"^player:(?P<name>[^#]+)#all_servers$")
RE_PLAYER_GLOBAL = re.compile(r"^player:(?P<name>[^#]+)#(?P<field>sotw_xp|botw_kills|dinklink)$")
RE_PLAYER_SERVER_FIELD = re.compile(
    r"^player:(?P<name>[^#]+)#server:(?P<sid>\d+)#(?P<field>member|mention|sotw_opt|botw_opt)$")
RE_MEMBER_PLAYERS = re.compile(r"^member:(?P<mid>\d+)#server:(?P<sid>\d+)#players$")


class Report:
    def __init__(self):
        self.counts = Counter()
        self.anomalies = []
        self.notes = []

    def anomaly(self, kind, detail):
        self.anomalies.append((kind, detail))

    def note(self, text):
        self.notes.append(text)

    def dump(self, stream=sys.stdout):
        w = stream.write
        w("\n" + "=" * 68 + "\n  MIGRATION REPORT\n" + "=" * 68 + "\n\n")
        w("  Rows written\n")
        for table in sorted(self.counts):
            w(f"    {table:<28} {self.counts[table]:>8,}\n")
        if self.notes:
            w("\n  Notes\n")
            for text in self.notes:
                w(f"    - {text}\n")
        if self.anomalies:
            grouped = defaultdict(list)
            for kind, detail in self.anomalies:
                grouped[kind].append(detail)
            w(f"\n  Anomalies ({len(self.anomalies)}) — pre-existing data issues, not errors\n")
            for kind in sorted(grouped):
                items = grouped[kind]
                w(f"    {kind} ({len(items)})\n")
                for detail in items[:8]:
                    w(f"        {detail}\n")
                if len(items) > 8:
                    w(f"        ... and {len(items) - 8} more\n")
        else:
            w("\n  No anomalies.\n")
        w("\n")


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #

class Migrator:
    def __init__(self, data_dir, conn, now, report):
        self.data_dir = data_dir
        self.conn = conn
        self.now = now
        self.rep = report

        self.player_ids = {}     # rs_name -> id
        self.skill_ids = {}      # name -> id
        self.activity_ids = {}   # name -> id
        self.server_ids = set()

    def quarantine(self, key, value, reason):
        """Park a key in legacy_kv so the reverse export can reproduce it.

        Only reason='unrecognised' aborts the migration. Everything else is a
        key the migration understands and has deliberately chosen not to model.
        """
        self.conn.execute(
            "INSERT INTO legacy_kv (key, value, reason) VALUES (?,?,?)",
            (key, json.dumps(value), reason))
        self.rep.counts["legacy_kv"] += 1

    # -- loading ----------------------------------------------------------- #

    def _load(self, *parts):
        path = os.path.join(self.data_dir, *parts)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def run(self):
        db_dis = self._load("db_discord.json")
        db_rs = self._load("db_runescape.json")

        classified = self.classify(db_dis)
        self.build_servers(classified)
        self.build_players(classified, db_rs)
        self.build_player_servers(classified)
        self.build_reference(db_rs)
        self.build_stats(db_rs)
        self.build_history(classified)
        self.build_config()
        self.cross_check(classified, db_rs)

        self.conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, self.now))
        self.conn.commit()

    # -- pass 1: classify every key ---------------------------------------- #

    def classify(self, db_dis):
        """Sort all 674 keys into buckets. Anything unmatched goes to legacy_kv."""
        out = {
            "active": [], "removed": [], "dinklinks": [],
            "server_field": defaultdict(dict),
            "server_players": {},
            "history": defaultdict(dict),
            "player_servers_list": {},
            "player_global": defaultdict(dict),
            "player_server_field": defaultdict(dict),
            "member_players": {},
            "unknown": {},
        }

        for key, value in db_dis.items():
            if key == "active_servers":
                out["active"] = value
                continue
            if key == "removed_servers":
                out["removed"] = value
                continue
            if key == "dinklinks":
                out["dinklinks"] = value
                continue

            match = RE_SERVER_FIELD.match(key)
            if match:
                out["server_field"][int(match["sid"])][match["field"]] = value
                continue
            match = RE_SERVER_PLAYERS.match(key)
            if match:
                out["server_players"][int(match["sid"])] = value
                continue
            match = RE_SERVER_HISTORY.match(key)
            if match:
                out["history"][match["kind"]][int(match["sid"])] = value
                continue
            match = RE_PLAYER_SERVERS.match(key)
            if match:
                out["player_servers_list"][match["name"]] = value
                continue
            match = RE_PLAYER_SERVER_FIELD.match(key)
            if match:
                pair = (match["name"], int(match["sid"]))
                out["player_server_field"][pair][match["field"]] = value
                continue
            match = RE_PLAYER_GLOBAL.match(key)
            if match:
                out["player_global"][match["name"]][match["field"]] = value
                continue
            match = RE_MEMBER_PLAYERS.match(key)
            if match:
                out["member_players"][(int(match["mid"]), int(match["sid"]))] = value
                continue

            out["unknown"][key] = value

        return out

    # -- pass 2: servers --------------------------------------------------- #

    def build_servers(self, cl):
        active = list(cl["active"])
        removed = list(cl["removed"])
        overlap = set(active) & set(removed)
        for sid in sorted(overlap):
            self.rep.anomaly("server in both active and removed", str(sid))

        every = set(active) | set(removed) | set(cl["server_field"]) | set(cl["server_players"])
        for kind in ("sotw", "botw"):
            every |= set(cl["history"][kind])

        rows = []
        for sid in sorted(every):
            fields = cl["server_field"].get(sid, {})
            if not fields:
                self.rep.anomaly("server referenced but has no settings keys", str(sid))
            is_active = 1 if sid in set(active) else 0
            rows.append((
                sid,
                fields.get("channel"),
                fields.get("role"),
                _as_bool(fields.get("sotw_opt")),
                _as_bool(fields.get("sotw_progress")),
                _as_bool(fields.get("botw_opt")),
                _as_bool(fields.get("botw_progress")),
                is_active,
                None if is_active else self.now,
            ))
            self.server_ids.add(sid)

        self.conn.executemany(
            "INSERT INTO servers (id, channel_id, role_id, sotw_opt, sotw_progress,"
            " botw_opt, botw_progress, is_active, removed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.rep.counts["servers"] = len(rows)

    # -- pass 3: players --------------------------------------------------- #

    def build_players(self, cl, db_rs):
        """A player exists if any player:<name># key mentions it.

        Deliberately NOT sourced from SOTW/BOTW history player names — a week
        from 2021 can name someone long since removed, and inventing rows for
        them would corrupt the round-trip. Those are stored as text instead.
        """
        names = set(cl["player_servers_list"]) | set(cl["player_global"])
        names |= {name for name, _ in cl["player_server_field"]}
        names |= set(db_rs)

        for name in sorted(db_rs):
            if name not in cl["player_servers_list"]:
                self.rep.anomaly("player has stats but no all_servers key", name)

        # Case-insensitive uniqueness is enforced by the schema; catch it here
        # with a better message than an IntegrityError.
        by_lower = defaultdict(list)
        for name in names:
            by_lower[name.lower()].append(name)
        for lowered, variants in sorted(by_lower.items()):
            if len(variants) > 1:
                self.rep.anomaly("player name differs only by case", ", ".join(sorted(variants)))

        rows = []
        for name in sorted(names):
            glob = cl["player_global"].get(name, {})
            rows.append((
                name,
                name_to_discord(name),
                glob.get("dinklink"),
                glob.get("sotw_xp", 0) or 0,
                glob.get("botw_kills", 0) or 0,
                # Presence in db_runescape.json, not presence of stats. Three
                # players are tracked with an empty skills dict; the old looper
                # polls them and the export must still emit their entry.
                1 if name in db_rs else 0,
                self.now,
            ))

        self.conn.executemany(
            "INSERT INTO players (rs_name, display_name, dink_link_key, sotw_xp,"
            " botw_kills, tracked, first_seen) VALUES (?,?,?,?,?,?,?)", rows)

        for rs_name, pid in self.conn.execute("SELECT rs_name, id FROM players"):
            self.player_ids[rs_name] = pid
        self.rep.counts["players"] = len(rows)

        ghosts = sorted(set(cl["player_servers_list"]) - set(db_rs))
        orphans = sorted(names - set(cl["player_servers_list"]))
        empty = sorted(n for n in db_rs if not db_rs[n].get("skills"))
        self.rep.note(f"{len(db_rs)} players are tracked (had a db_runescape entry)")
        if empty:
            self.rep.note(
                f"{len(empty)} of those are tracked with an EMPTY skills dict and stay "
                "pollable, matching current behaviour: " + ", ".join(empty))
        if ghosts:
            self.rep.note(
                f"{len(ghosts)} ghost players (in a server, no stats) stay unpollable: "
                + ", ".join(ghosts))
        if orphans:
            self.rep.note(
                f"{len(orphans)} orphan players (counters only, no servers): "
                + ", ".join(orphans))

    # -- pass 4: player <-> server links ----------------------------------- #

    def build_player_servers(self, cl):
        """all_servers is the ONLY source of truth for whether a link exists.

        That is what the bot itself uses: LoopPlayerHandler.get_all_player_info()
        and DinkPlayerHandler both iterate player:<name>#all_servers and never
        consult the per-server field keys to decide membership.

        The two do disagree in practice. A couple of players still carry a
        stray `#server:<id>#sotw_opt` from a removal that did not clean up
        fully — remove_player() deletes member/mention/sotw_opt/botw_opt, but
        some rows predate part of that. They are dead data: the server is not in
        those players' all_servers, so nothing ever reads them.

        Building links from the union instead would re-attach those players to a
        server they were removed from, and the looper would start posting their
        updates there. So field keys without an all_servers entry are
        quarantined in legacy_kv rather than promoted to rows.
        """
        pairs = set()
        for name, servers in cl["player_servers_list"].items():
            if not servers:
                # The export decides whether to emit an all_servers key by
                # whether any link rows exist, which relies on empty lists never
                # persisting. remove_player() deletes the key when it empties.
                self.rep.anomaly("player has an empty all_servers list", name)
            for sid in servers:
                pairs.add((name, int(sid)))

        rows = []
        for name, sid in sorted(pairs):
            if sid not in self.server_ids:
                self.rep.anomaly("link points at an unknown server", f"{name} @ {sid}")
                continue
            fields = cl["player_server_field"].get((name, sid), {})
            rows.append((
                self.player_ids[name], sid,
                fields.get("member"),
                _as_bool(fields.get("mention")),
                _as_bool(fields.get("sotw_opt")),
                _as_bool(fields.get("botw_opt")),
            ))

        self.conn.executemany(
            "INSERT INTO player_servers (player_id, server_id, member_id, mention,"
            " sotw_opt, botw_opt) VALUES (?,?,?,?,?,?)", rows)
        self.rep.counts["player_servers"] = len(rows)

        orphaned = sorted(set(cl["player_server_field"]) - pairs)
        for name, sid in orphaned:
            for field, value in sorted(cl["player_server_field"][(name, sid)].items()):
                self.quarantine(f"player:{name}#server:{sid}#{field}", value,
                                "orphaned-player-server-field")
            self.rep.anomaly(
                "per-server fields for a player not linked to that server (dead data)",
                f"{name} @ {sid}: "
                + ", ".join(sorted(cl["player_server_field"][(name, sid)])))

    # -- pass 5: reference tables ------------------------------------------ #

    def build_reference(self, db_rs):
        skills, activities = set(), set()
        for stats in db_rs.values():
            skills |= set(stats.get("skills", {}))
            activities |= set(stats.get("minigames", {}))

        # Seed from the pools too, so a skill nobody has trained still exists.
        try:
            skills |= set(self._load("sotw", "all_skills.json")["all_skills"])
        except (OSError, KeyError):
            self.rep.anomaly("could not seed skills", "data/sotw/all_skills.json")
        try:
            activities |= set(self._load("botw", "all_bosses.json")["all_bosses"])
        except (OSError, KeyError):
            self.rep.anomaly("could not seed activities", "data/botw/all_bosses.json")

        def order_of(name):
            return SKILL_ORDER.index(name) if name in SKILL_ORDER else None

        skill_rows = sorted(skills, key=lambda n: (order_of(n) is None, order_of(n) or 0, n))
        self.conn.executemany(
            "INSERT INTO skills (name, sort_order) VALUES (?,?)",
            [(n, order_of(n)) for n in skill_rows])
        activity_rows = sorted(activities)
        self.conn.executemany(
            "INSERT INTO activities (name, sort_order) VALUES (?,?)",
            [(n, i) for i, n in enumerate(activity_rows)])

        for name, sid in self.conn.execute("SELECT name, id FROM skills"):
            self.skill_ids[name] = sid
        for name, aid in self.conn.execute("SELECT name, id FROM activities"):
            self.activity_ids[name] = aid
        self.rep.counts["skills"] = len(skill_rows)
        self.rep.counts["activities"] = len(activity_rows)

        unknown = [n for n in skills if n not in SKILL_ORDER]
        if unknown:
            self.rep.note("skills with no known hiscores position: " + ", ".join(sorted(unknown)))

    # -- pass 6: current stats, plus one seed history row each ------------- #

    def build_stats(self, db_rs):
        skill_rows, activity_rows = [], []

        for rs_name, stats in db_rs.items():
            pid = self.player_ids[rs_name]

            for skill, values in stats.get("skills", {}).items():
                level = parse_hiscore_value(values.get("level"))
                xp = parse_hiscore_value(values.get("xp"))
                rank = parse_hiscore_value(values.get("rank"))
                if level is None or xp is None:
                    # Measured invariant: '--' appears in rank only, never in
                    # level/xp/score. If that breaks, do not guess.
                    self.rep.anomaly(
                        "skill row missing level or xp",
                        f"{rs_name} / {skill} -> {values!r}")
                    continue
                skill_rows.append((pid, self.skill_ids[skill], level, xp, rank, self.now))

            for activity, values in stats.get("minigames", {}).items():
                score = parse_hiscore_value(values.get("score"))
                rank = parse_hiscore_value(values.get("rank"))
                if score is None:
                    self.rep.anomaly(
                        "activity row missing score",
                        f"{rs_name} / {activity} -> {values!r}")
                    continue
                activity_rows.append((pid, self.activity_ids[activity], score, rank, self.now))

        self.conn.executemany(
            "INSERT INTO player_skill_current (player_id, skill_id, level, xp, rank,"
            " updated_at) VALUES (?,?,?,?,?,?)", skill_rows)
        self.conn.executemany(
            "INSERT INTO player_activity_current (player_id, activity_id, score, rank,"
            " updated_at) VALUES (?,?,?,?,?)", activity_rows)

        # Seed history so a chart has an origin point. There is no historical XP
        # anywhere in the JSON to backfill; these are all stamped `now`.
        self.conn.executemany(
            "INSERT INTO player_skill_history (player_id, skill_id, level, xp, rank,"
            " recorded_at) VALUES (?,?,?,?,?,?)", skill_rows)
        self.conn.executemany(
            "INSERT INTO player_activity_history (player_id, activity_id, score, rank,"
            " recorded_at) VALUES (?,?,?,?,?)", activity_rows)

        self.rep.counts["player_skill_current"] = len(skill_rows)
        self.rep.counts["player_activity_current"] = len(activity_rows)
        self.rep.counts["player_skill_history (seed)"] = len(skill_rows)
        self.rep.counts["player_activity_history (seed)"] = len(activity_rows)

    # -- pass 7: SOTW / BOTW history --------------------------------------- #

    def build_history(self, cl):
        spec = {
            "sotw": ("sotw_weeks", "sotw_week_players", "skill", "skill_name", "xp"),
            "botw": ("botw_weeks", "botw_week_players", "boss", "boss_name", "kills"),
        }

        for kind, (week_tbl, wp_tbl, json_key, name_col, score_col) in spec.items():
            weeks_written = players_written = 0

            for sid, weeks in sorted(cl["history"][kind].items()):
                for seq, week in enumerate(weeks):
                    ended_on = self._iso_date(week.get("date"), f"{kind} week {sid}#{seq}")
                    cur = self.conn.execute(
                        f"INSERT INTO {week_tbl} (server_id, {name_col}, ended_on, seq)"
                        " VALUES (?,?,?,?)",
                        (sid, week.get(json_key), ended_on, seq))
                    week_id = cur.lastrowid
                    weeks_written += 1

                    for pseq, entry in enumerate(week.get("players", [])):
                        pname = entry.get("player")
                        self.conn.execute(
                            f"INSERT INTO {wp_tbl} (week_id, player_id, player_name,"
                            f" {score_col}, rank, seq) VALUES (?,?,?,?,?,?)",
                            (week_id,
                             self.player_ids.get(pname),   # NULL when long removed
                             pname,
                             entry.get(score_col),
                             entry.get("rank"),
                             pseq))
                        players_written += 1

            self.rep.counts[week_tbl] = weeks_written
            self.rep.counts[wp_tbl] = players_written

        missing = self.conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT player_name FROM sotw_week_players WHERE player_id IS NULL"
            "  UNION ALL"
            "  SELECT player_name FROM botw_week_players WHERE player_id IS NULL)"
        ).fetchone()[0]
        if missing:
            self.rep.note(
                f"{missing} history placements name a player that no longer exists; "
                "kept as text with player_id NULL")

    def _iso_date(self, raw, where):
        if not raw:
            self.rep.anomaly("history week with no date", where)
            return ""
        try:
            return datetime.strptime(raw, JSON_DATE_FMT).date().isoformat()
        except ValueError:
            # Keep it verbatim rather than guessing; the export passes through
            # anything it cannot re-format.
            self.rep.anomaly("unparseable history date", f"{where}: {raw!r}")
            return raw

    # -- pass 8: config ---------------------------------------------------- #

    def build_config(self):
        for key, parts in (("sotw", ("sotw", "sotw_config.json")),
                           ("botw", ("botw", "botw_config.json"))):
            try:
                blob = self._load(*parts)
            except OSError:
                self.rep.anomaly("missing config file", "/".join(parts))
                continue
            self.conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?,?)",
                (f"{key}_config", json.dumps(blob, sort_keys=False)))
            self.rep.counts["app_config"] += 1

    # -- pass 9: leftovers and consistency --------------------------------- #

    def cross_check(self, cl, db_rs):
        # dinklinks list vs players.dink_link_key
        listed = set(cl["dinklinks"])
        stored = {row[0] for row in self.conn.execute(
            "SELECT dink_link_key FROM players WHERE dink_link_key IS NOT NULL")}
        # Keys are bearer tokens — report counts and player names, never values.
        if listed - stored:
            self.rep.anomaly("dinklinks in the index list but on no player",
                             f"{len(listed - stored)} key(s)")
        if stored - listed:
            self.rep.anomaly("dinklinks on a player but missing from the index list",
                             f"{len(stored - listed)} key(s)")

        # Two accounts sharing one key is untidy but harmless: the webhook
        # authenticates with the key and then routes on payload['playerName'].
        # Worth surfacing so it can be cleaned up with ;dinklink.
        for row in self.conn.execute(
                "SELECT GROUP_CONCAT(rs_name, ', ') AS names, COUNT(*) AS n"
                " FROM players WHERE dink_link_key IS NOT NULL"
                " GROUP BY dink_link_key HAVING n > 1"):
            self.rep.anomaly("one dinklink shared by several players", row["names"])

        # server all_players vs the link rows
        for sid, names in cl["server_players"].items():
            actual = {row[0] for row in self.conn.execute(
                "SELECT p.rs_name FROM player_servers ps"
                " JOIN players p ON p.id = ps.player_id WHERE ps.server_id = ?", (sid,))}
            for name in sorted(set(names) - actual):
                self.rep.anomaly("in server all_players but not linked", f"{name} @ {sid}")
            for name in sorted(actual - set(names)):
                self.rep.anomaly("linked but not in server all_players", f"{name} @ {sid}")
            for name in sorted(set(names) - set(db_rs)):
                self.rep.anomaly("in server all_players with no stats (ghost)", f"{name} @ {sid}")

        # member -> players lists are derivable; verify before discarding them
        for (mid, sid), names in cl["member_players"].items():
            actual = {row[0] for row in self.conn.execute(
                "SELECT p.rs_name FROM player_servers ps"
                " JOIN players p ON p.id = ps.player_id"
                " WHERE ps.server_id = ? AND ps.member_id = ?", (sid, mid))}
            if actual != set(names):
                self.rep.anomaly(
                    "member player list disagrees with links",
                    f"member {mid} @ {sid}: json={sorted(names)} db={sorted(actual)}")

        # leftovers
        for key, value in sorted(cl["unknown"].items()):
            self.quarantine(key, value, "unrecognised")


def _as_bool(value):
    """Preserve absence. NULL means the JSON key was missing, which every read
    path coalesces to True — matching the try/except the bot uses today."""
    if value is None:
        return None
    return 1 if value else 0


# --------------------------------------------------------------------------- #

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data",
                        help="directory holding db_discord.json etc (default: data)")
    parser.add_argument("--schema", default=None,
                        help="path to schema.sql (default: <data-dir>/schema.sql)")
    parser.add_argument("--db", default=None,
                        help="output database (default: <data-dir>/osrs.db)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing database file")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="do not abort on unrecognised db_discord.json keys")
    parser.add_argument("--report", action="store_true",
                        help="migrate to a temporary in-memory DB and only print the report")
    parser.add_argument("--now", default=None,
                        help="ISO timestamp to stamp rows with (default: now, UTC)")
    args = parser.parse_args(argv)

    # The schema ships with the code, not with the state, so a fixture pulled
    # from the server has no schema.sql in it. Prefer one alongside the data if
    # it is there, otherwise fall back to the repo's.
    schema_path = args.schema
    if schema_path is None:
        beside_data = os.path.join(args.data_dir, "schema.sql")
        schema_path = (beside_data if os.path.exists(beside_data)
                       else os.path.join("data", "schema.sql"))
    db_path = args.db or os.path.join(args.data_dir, "osrs.db")
    now = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not os.path.isdir(args.data_dir):
        parser.error(f"no such data directory: {args.data_dir!r} "
                     "(run this from the inner osrs-event-log directory)")
    if not os.path.exists(schema_path):
        parser.error(f"no schema at {schema_path!r}")

    if args.report:
        db_path = ":memory:"
    elif os.path.exists(db_path):
        if not args.force:
            parser.error(f"{db_path} already exists; pass --force to replace it")
        os.remove(db_path)

    with open(schema_path, "r", encoding="utf-8") as handle:
        schema_sql = handle.read()

    report = Report()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(schema_sql)
        # Constraints stay off during the load so that a data problem surfaces
        # as a readable anomaly rather than an IntegrityError halfway through.
        # foreign_key_check below is the real gate.
        conn.execute("PRAGMA foreign_keys = OFF")
        Migrator(args.data_dir, conn, now, report).run()

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

        blocking = [k for k in
                    (row[0] for row in conn.execute(
                        "SELECT key FROM legacy_kv WHERE reason = 'unrecognised'"))
                    if not any(pattern.match(k) for pattern in LEGACY_ALLOWLIST)]

        report.dump()

        if violations:
            print(f"  FAILED: {len(violations)} foreign key violations", file=sys.stderr)
            for row in violations[:10]:
                print(f"    {row}", file=sys.stderr)
            return 1
        if integrity != "ok":
            print(f"  FAILED: integrity_check said {integrity!r}", file=sys.stderr)
            return 1
        if blocking and not args.allow_unknown:
            print(f"  FAILED: {len(blocking)} unrecognised db_discord.json keys.\n"
                  "  These were NOT migrated into any table. Either teach the migration\n"
                  "  about them or re-run with --allow-unknown to accept the loss:",
                  file=sys.stderr)
            for key in blocking[:20]:
                print(f"    {key}", file=sys.stderr)
            return 1

        if args.report:
            print("  (--report: nothing written)\n")
        else:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("VACUUM")
            size = os.path.getsize(db_path)
            print(f"  Wrote {db_path} ({size:,} bytes)\n")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

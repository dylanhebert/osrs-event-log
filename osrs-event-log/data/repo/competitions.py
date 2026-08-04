"""Skill of the Week and Boss of the Week.

The two are structurally identical — same tables, same queries, different column
names — so everything here is parameterised on `kind` ('sotw' or 'botw') rather
than duplicated, which is what the JSON handlers did (sotw.py and botw.py are
near-identical 380-line files).

Config stays as a JSON blob per competition. The bot reads and replaces those
dicts wholesale (SOTW_CONFIG is a module global swapped out by
update_sotw_config), so splitting it into columns would add drift risk for no
gain. Query into it with json_extract(value, '$.current_skill') if the web UI
needs a field.
"""

import json
from datetime import datetime

from . import db

JSON_DATE_FMT = "%m-%d-%y"

_SPEC = {
    "sotw": {
        "weeks": "sotw_weeks", "week_players": "sotw_week_players",
        "name_col": "skill_name", "score_col": "xp",
        "player_col": "sotw_xp", "opt_col": "sotw_opt", "json_name": "skill",
    },
    "botw": {
        "weeks": "botw_weeks", "week_players": "botw_week_players",
        "name_col": "boss_name", "score_col": "kills",
        "player_col": "botw_kills", "opt_col": "botw_opt", "json_name": "boss",
    },
}

TOP_PLAYERS_COUNT = 10


def spec(kind):
    if kind not in _SPEC:
        raise ValueError(f"not a competition: {kind!r}")
    return _SPEC[kind]


def _to_iso(value):
    try:
        return datetime.strptime(value, JSON_DATE_FMT).date().isoformat()
    except (ValueError, TypeError):
        return value


def _from_iso(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime(JSON_DATE_FMT)
    except (ValueError, TypeError):
        return value


# --------------------------------------------------------------------------- #
# Standings in progress
# --------------------------------------------------------------------------- #

def top_players(server_id, kind, limit=TOP_PLAYERS_COUNT):
    """Current leaders in one server. Players on zero are excluded, matching
    get_sotw_top_players(). Also respects each player's per-server opt-out,
    which the JSON version checked separately (and inconsistently)."""
    conf = spec(kind)
    rows = db.query(
        f"SELECT p.rs_name, p.{conf['player_col']} AS score FROM player_servers ps"
        " JOIN players p ON p.id = ps.player_id"
        f" WHERE ps.server_id = ? AND p.{conf['player_col']} > 0"
        f" ORDER BY p.{conf['player_col']} DESC, p.rs_name LIMIT ?",
        (server_id, limit))
    key = "xp" if kind == "sotw" else "kills"
    return [{"player": r["rs_name"], key: r["score"]} for r in rows]


def reset_scores(kind):
    """Zero every player's running total. Ends a week."""
    conf = spec(kind)
    db.execute(f"UPDATE players SET {conf['player_col']} = 0")


# --------------------------------------------------------------------------- #
# Completed weeks
# --------------------------------------------------------------------------- #

def record_week(server_id, kind, name, ended_on, placements):
    """Append a finished week. `placements` is the top-3 list in rank order:
    [{'player': rs_name, 'xp'|'kills': n, 'rank': 1}, ...]"""
    conf = spec(kind)
    score_col = conf["score_col"]
    with db.transaction():
        seq = db.scalar(
            f"SELECT COALESCE(MAX(seq) + 1, 0) FROM {conf['weeks']} WHERE server_id = ?",
            (server_id,), 0)
        cur = db.execute(
            f"INSERT INTO {conf['weeks']} (server_id, {conf['name_col']}, ended_on, seq)"
            " VALUES (?,?,?,?)", (server_id, name, _to_iso(ended_on), seq))
        week_id = cur.lastrowid
        for pseq, entry in enumerate(placements):
            rs_name = entry["player"]
            db.execute(
                f"INSERT INTO {conf['week_players']} (week_id, player_id, player_name,"
                f" {score_col}, rank, seq) VALUES (?,?,?,?,?,?)",
                (week_id,
                 db.scalar("SELECT id FROM players WHERE rs_name = ?", (rs_name,)),
                 rs_name, entry.get(score_col), entry.get("rank"), pseq))
        return week_id


def history(server_id, kind):
    """Every completed week, oldest first — the shape get_sotw_history() walked:
    [{'date': '05-12-21', 'skill'|'boss': str, 'players': [...]}, ...]"""
    conf = spec(kind)
    score_col = conf["score_col"]
    weeks = []
    for week in db.query(
            f"SELECT id, {conf['name_col']} AS label, ended_on FROM {conf['weeks']}"
            " WHERE server_id = ? ORDER BY seq", (server_id,)):
        players = [
            {"player": r["player_name"], score_col: r[score_col], "rank": r["rank"]}
            for r in db.query(
                f"SELECT player_name, {score_col}, rank FROM {conf['week_players']}"
                " WHERE week_id = ? ORDER BY seq", (week["id"],))]
        weeks.append({"date": _from_iso(week["ended_on"]),
                      conf["json_name"]: week["label"],
                      "players": players})
    return weeks


def standings(server_id, kind):
    """Trophy totals, sorted by weighted score.

    The JSON version rebuilt this in Python on every `;sotw stats` call by
    looping all 288 of a server's weeks. Here it is one grouped query against
    v_sotw_standings / v_botw_standings.
    """
    view = f"v_{kind}_standings"
    spec(kind)  # validate
    total_col = "xp_all" if kind == "sotw" else "kills_all"
    rows = db.query(
        f"SELECT player_name, {total_col} AS total, rank_1, rank_2, rank_3, rank_weight"
        f" FROM {view} WHERE server_id = ?"
        " ORDER BY rank_weight DESC, total DESC, player_name", (server_id,))
    from .players import name_to_discord
    return [{"name": name_to_discord(r["player_name"]),
             "rs_name": r["player_name"],
             total_col: r["total"],
             "rank_1": r["rank_1"], "rank_2": r["rank_2"], "rank_3": r["rank_3"],
             "rank_weight": r["rank_weight"]} for r in rows]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def get_config(kind):
    spec(kind)
    raw = db.scalar("SELECT value FROM app_config WHERE key = ?", (f"{kind}_config",))
    return json.loads(raw) if raw else {}


def set_config(kind, config):
    spec(kind)
    db.execute(
        "INSERT INTO app_config (key, value) VALUES (?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"{kind}_config", json.dumps(config, sort_keys=False)))
    return config

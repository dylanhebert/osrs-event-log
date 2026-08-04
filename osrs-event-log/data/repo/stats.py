"""Player hiscores stats: current values and the append-only history.

THE CHANGE-DETECTION CONTRACT
-----------------------------
get_player_stats() returns exactly the structure the JSON version held:

    {'skills':    {'Attack': {'rank': int|None, 'level': int, 'xp': int}, ...},
     'minigames': {'Zulrah': {'rank': int|None, 'score': int}, ...}}

The only difference is the value type. The JSON stored comma-formatted strings
("102,315,637") because the scraped HTML page rendered them that way, and '--'
for unranked. Those are now real integers, with None for unranked.

common/util.py get_player_scores() produces the same int-valued shape from
index_lite.json, so the looper compares int to int. That is *more* robust than
the old string comparison, which depended on hiscore_value() reformatting the
API's raw ints back into the exact string the file happened to hold — any drift
there and every skill of every player reads as changed, and the bot posts a
milestone for all of them in every server.

`rank` is never used for change detection, only printed. It drifts by a place or
two between any two fetches.

HISTORY
-------
apply_changes() writes the _current update and the _history row in one
transaction, and only for values that actually moved. That is what keeps history
affordable (~400k rows/year rather than ~45M) and what stops the two tables
drifting apart.
"""

from . import db

# Reference-table caches. Names are stable and few (25 skills, ~90 activities),
# and the looper asks for them thousands of times per poll cycle.
_skill_ids = {}
_activity_ids = {}


def reset_caches():
    _skill_ids.clear()
    _activity_ids.clear()


def _lookup(table, cache, name):
    if not cache:
        for row in db.query(f"SELECT id, name FROM {table}"):
            cache[row["name"]] = row["id"]
    if name in cache:
        return cache[name]
    # Jagex adds things — Sailing is recent, and new bosses arrive regularly.
    # An unknown name is expected, not an error.
    cur = db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    cache[name] = cur.lastrowid
    return cache[name]


def skill_id(name):
    return _lookup("skills", _skill_ids, name)


def activity_id(name):
    return _lookup("activities", _activity_ids, name)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def get_player_stats(player_id):
    """The dict the looper compares against. Ints, not formatted strings."""
    skills = {}
    for row in db.query(
            "SELECT sk.name, c.level, c.xp, c.rank FROM player_skill_current c"
            " JOIN skills sk ON sk.id = c.skill_id WHERE c.player_id = ?", (player_id,)):
        skills[row["name"]] = {"rank": row["rank"], "level": row["level"], "xp": row["xp"]}

    minigames = {}
    for row in db.query(
            "SELECT a.name, c.score, c.rank FROM player_activity_current c"
            " JOIN activities a ON a.id = c.activity_id WHERE c.player_id = ?",
            (player_id,)):
        minigames[row["name"]] = {"rank": row["rank"], "score": row["score"]}

    return {"skills": skills, "minigames": minigames}


def load_all_pollable():
    """{rs_name: stats_dict} for every pollable player.

    Replaces LoopPlayerHandler.data_runescape. Built from the pollable_players
    view, so the 12 ghost players stay out — see the view's comment in
    schema.sql for why that matters.

    Two queries total rather than one per player: at 69 players x 112 rows this
    is a few milliseconds.
    """
    players = {row["id"]: row["rs_name"] for row in db.query(
        "SELECT id, rs_name FROM pollable_players ORDER BY rs_name")}
    if not players:
        return {}

    out = {name: {"skills": {}, "minigames": {}} for name in players.values()}
    placeholders = ",".join("?" * len(players))
    ids = list(players)

    for row in db.query(
            "SELECT c.player_id, sk.name, c.level, c.xp, c.rank"
            " FROM player_skill_current c JOIN skills sk ON sk.id = c.skill_id"
            f" WHERE c.player_id IN ({placeholders})", ids):
        out[players[row["player_id"]]]["skills"][row["name"]] = {
            "rank": row["rank"], "level": row["level"], "xp": row["xp"]}

    for row in db.query(
            "SELECT c.player_id, a.name, c.score, c.rank"
            " FROM player_activity_current c JOIN activities a ON a.id = c.activity_id"
            f" WHERE c.player_id IN ({placeholders})", ids):
        out[players[row["player_id"]]]["minigames"][row["name"]] = {
            "rank": row["rank"], "score": row["score"]}

    return out


def overall_xp(player_id):
    return db.scalar(
        "SELECT c.xp FROM player_skill_current c JOIN skills sk ON sk.id = c.skill_id"
        " WHERE c.player_id = ? AND sk.name = 'Overall'", (player_id,))


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def apply_changes(player_id, stats, now=None):
    """Persist a player's stats, writing history only where a value moved.

    `stats` is the same shape get_player_stats() returns. Values already present
    with identical numbers are left alone entirely — no UPDATE, no history row.

    Returns (skill_writes, activity_writes) so the caller can log how much
    actually changed. A healthy poll cycle writes single digits.
    """
    now = now or db.utcnow()
    existing = get_player_stats(player_id)
    skill_writes = activity_writes = 0

    with db.transaction():
        for name, values in stats.get("skills", {}).items():
            was = existing["skills"].get(name)
            # rank is excluded from the comparison on purpose: it drifts between
            # any two fetches and would make every player look changed.
            if was is not None and was["level"] == values["level"] and was["xp"] == values["xp"]:
                continue
            sid = skill_id(name)
            db.execute(
                "INSERT INTO player_skill_current (player_id, skill_id, level, xp,"
                " rank, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(player_id, skill_id) DO UPDATE SET"
                "   level = excluded.level, xp = excluded.xp,"
                "   rank = excluded.rank, updated_at = excluded.updated_at",
                (player_id, sid, values["level"], values["xp"], values.get("rank"), now))
            db.execute(
                "INSERT INTO player_skill_history (player_id, skill_id, level, xp,"
                " rank, recorded_at) VALUES (?,?,?,?,?,?)",
                (player_id, sid, values["level"], values["xp"], values.get("rank"), now))
            skill_writes += 1

        for name, values in stats.get("minigames", {}).items():
            was = existing["minigames"].get(name)
            if was is not None and was["score"] == values["score"]:
                continue
            aid = activity_id(name)
            db.execute(
                "INSERT INTO player_activity_current (player_id, activity_id, score,"
                " rank, updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(player_id, activity_id) DO UPDATE SET"
                "   score = excluded.score, rank = excluded.rank,"
                "   updated_at = excluded.updated_at",
                (player_id, aid, values["score"], values.get("rank"), now))
            db.execute(
                "INSERT INTO player_activity_history (player_id, activity_id, score,"
                " rank, recorded_at) VALUES (?,?,?,?,?)",
                (player_id, aid, values["score"], values.get("rank"), now))
            activity_writes += 1

        db.execute("UPDATE players SET last_polled = ?, tracked = 1 WHERE id = ?",
                   (now, player_id))

    return skill_writes, activity_writes


def replace_all(player_id, stats, now=None):
    """Set a player's stats wholesale, for ;add and ;transfer.

    Unlike apply_changes() this seeds history for every value, because there is
    no prior state to diff against — it is the player's first snapshot.
    """
    now = now or db.utcnow()
    with db.transaction():
        db.execute("DELETE FROM player_skill_current WHERE player_id = ?", (player_id,))
        db.execute("DELETE FROM player_activity_current WHERE player_id = ?", (player_id,))
        for name, values in stats.get("skills", {}).items():
            sid = skill_id(name)
            row = (player_id, sid, values["level"], values["xp"], values.get("rank"), now)
            db.execute(
                "INSERT INTO player_skill_current (player_id, skill_id, level, xp,"
                " rank, updated_at) VALUES (?,?,?,?,?,?)", row)
            db.execute(
                "INSERT INTO player_skill_history (player_id, skill_id, level, xp,"
                " rank, recorded_at) VALUES (?,?,?,?,?,?)", row)
        for name, values in stats.get("minigames", {}).items():
            aid = activity_id(name)
            row = (player_id, aid, values["score"], values.get("rank"), now)
            db.execute(
                "INSERT INTO player_activity_current (player_id, activity_id, score,"
                " rank, updated_at) VALUES (?,?,?,?,?)", row)
            db.execute(
                "INSERT INTO player_activity_history (player_id, activity_id, score,"
                " rank, recorded_at) VALUES (?,?,?,?,?)", row)
        db.execute("UPDATE players SET tracked = 1, last_polled = ? WHERE id = ?",
                   (now, player_id))


# --------------------------------------------------------------------------- #
# History reads — for the future web UI
# --------------------------------------------------------------------------- #

def skill_series(player_id, skill_name, since=None, limit=1000):
    sql = ("SELECT h.level, h.xp, h.rank, h.recorded_at FROM player_skill_history h"
           " JOIN skills sk ON sk.id = h.skill_id"
           " WHERE h.player_id = ? AND sk.name = ?")
    params = [player_id, skill_name]
    if since:
        sql += " AND h.recorded_at >= ?"
        params.append(since)
    return db.query(sql + " ORDER BY h.recorded_at LIMIT ?", params + [limit])


def activity_series(player_id, activity_name, since=None, limit=1000):
    sql = ("SELECT h.score, h.rank, h.recorded_at FROM player_activity_history h"
           " JOIN activities a ON a.id = h.activity_id"
           " WHERE h.player_id = ? AND a.name = ?")
    params = [player_id, activity_name]
    if since:
        sql += " AND h.recorded_at >= ?"
        params.append(since)
    return db.query(sql + " ORDER BY h.recorded_at LIMIT ?", params + [limit])

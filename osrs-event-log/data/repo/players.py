"""Players, and their links to Discord servers and members.

Everything here takes plain ids and strings — no discord.py objects. That is
what lets the future read-only web UI import this module directly, and what lets
the test harness run without a bot token or a Discord connection.

`rs_name` is always the RS form with '+' for spaces ("Amber+Quill"), matching
the old JSON keys. The column is COLLATE NOCASE, so lookups are case-insensitive
and a differently-cased RSN from Dink cannot create a duplicate player.
"""

from . import db


def name_to_discord(rs_name):
    """Mirror of common/util.py name_to_discord(). Duplicated so this module
    stays free of the bot's imports (util pulls in discord and aiohttp)."""
    if "+" in rs_name:
        return rs_name.title().replace("+", " ")
    return rs_name.title()


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #

def get_id(rs_name):
    return db.scalar("SELECT id FROM players WHERE rs_name = ?", (rs_name,))


def get(rs_name):
    return db.one("SELECT * FROM players WHERE rs_name = ?", (rs_name,))


def exists(rs_name):
    return get_id(rs_name) is not None


def ensure(rs_name, tracked=False):
    """Return the player's id, creating the row if needed."""
    player_id = get_id(rs_name)
    if player_id is not None:
        if tracked:
            db.execute("UPDATE players SET tracked = 1 WHERE id = ?", (player_id,))
        return player_id
    cur = db.execute(
        "INSERT INTO players (rs_name, display_name, tracked, first_seen)"
        " VALUES (?, ?, ?, ?)",
        (rs_name, name_to_discord(rs_name), 1 if tracked else 0, db.utcnow()))
    return cur.lastrowid


def pollable():
    """The players the looper should poll, in the order it used to see them.

    Selects from the pollable_players view, never from `players`. See the long
    comment on that view in schema.sql: selecting from `players` would pick up
    12 ghost players that have never been polled, every skill would read as new,
    and the bot would post "first time on the Hiscores" for all of them.
    """
    return db.query("SELECT id, rs_name FROM pollable_players ORDER BY rs_name")


def touch_polled(player_id, when=None):
    db.execute("UPDATE players SET last_polled = ? WHERE id = ?",
               (when or db.utcnow(), player_id))


# --------------------------------------------------------------------------- #
# Server links
# --------------------------------------------------------------------------- #

def active_links(rs_name):
    """Servers a player is in, restricted to servers the bot is still in.

    Replaces LoopPlayerHandler.get_all_player_info() and the Dink equivalent.
    Returns the same list-of-dicts shape those returned, so the cogs need no
    change: [{'server': int, 'member': int, 'mention': bool}, ...]

    `mention` coalesces NULL to True — NULL means the JSON key was absent, which
    the old code treated as truthy via try/except.
    """
    rows = db.query(
        "SELECT ps.server_id, ps.member_id, COALESCE(ps.mention, 1) AS mention"
        " FROM player_servers ps"
        " JOIN players p ON p.id = ps.player_id"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE p.rs_name = ? AND s.is_active = 1"
        " ORDER BY ps.server_id", (rs_name,))
    return [{"server": r["server_id"],
             "member": r["member_id"],
             "mention": bool(r["mention"])} for r in rows]


def link(rs_name, server_id):
    return db.one(
        "SELECT ps.* FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        " WHERE p.rs_name = ? AND ps.server_id = ?", (rs_name, server_id))


def server_ids(rs_name):
    """Every server, active or not — the old `all_servers` list."""
    return [r["server_id"] for r in db.query(
        "SELECT ps.server_id FROM player_servers ps"
        " JOIN players p ON p.id = ps.player_id"
        " WHERE p.rs_name = ? ORDER BY ps.server_id", (rs_name,))]


def member_players(server_id, member_id):
    """The players one member uses in one server — was member:<id>#server:<id>#players."""
    return [r["rs_name"] for r in db.query(
        "SELECT p.rs_name FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        " WHERE ps.server_id = ? AND ps.member_id = ? ORDER BY p.rs_name",
        (server_id, member_id))]


def linked_member(rs_name, server_id):
    return db.scalar(
        "SELECT ps.member_id FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        " WHERE p.rs_name = ? AND ps.server_id = ?", (rs_name, server_id))


def add_link(rs_name, server_id, member_id, mention=True,
             sotw_opt=True, botw_opt=True):
    player_id = ensure(rs_name)
    db.execute(
        "INSERT INTO player_servers (player_id, server_id, member_id, mention,"
        " sotw_opt, botw_opt) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(player_id, server_id) DO UPDATE SET"
        "   member_id = excluded.member_id, mention = excluded.mention,"
        "   sotw_opt = excluded.sotw_opt, botw_opt = excluded.botw_opt",
        (player_id, server_id, member_id, int(mention), int(sotw_opt), int(botw_opt)))
    return player_id


def remove_link(rs_name, server_id):
    db.execute(
        "DELETE FROM player_servers WHERE server_id = ? AND player_id ="
        " (SELECT id FROM players WHERE rs_name = ?)", (server_id, rs_name))


def get_link_option(rs_name, server_id, field):
    """field is one of mention / sotw_opt / botw_opt. NULL reads as True."""
    _check_link_field(field)
    return bool(db.scalar(
        f"SELECT COALESCE(ps.{field}, 1) FROM player_servers ps"
        " JOIN players p ON p.id = ps.player_id"
        " WHERE p.rs_name = ? AND ps.server_id = ?", (rs_name, server_id), 1))


def set_link_option(rs_name, server_id, field, value):
    _check_link_field(field)
    db.execute(
        f"UPDATE player_servers SET {field} = ? WHERE server_id = ? AND player_id ="
        " (SELECT id FROM players WHERE rs_name = ?)",
        (int(bool(value)), server_id, rs_name))
    return bool(value)


def _check_link_field(field):
    # These are interpolated into SQL, so they are checked against a fixed set
    # rather than passed through. The handler layer forwards a caller-supplied
    # `entry` string here (toggle_player_entry), so this is not decorative.
    if field not in ("mention", "sotw_opt", "botw_opt"):
        raise ValueError(f"not a player-server option: {field!r}")


# --------------------------------------------------------------------------- #
# Global per-player values
# --------------------------------------------------------------------------- #

_GLOBAL_FIELDS = ("sotw_xp", "botw_kills")


def get_global(rs_name, field):
    _check_global_field(field)
    return db.scalar(f"SELECT {field} FROM players WHERE rs_name = ?", (rs_name,), 0)


def set_global(rs_name, field, value):
    _check_global_field(field)
    db.execute(f"UPDATE players SET {field} = ? WHERE rs_name = ?", (value, rs_name))
    return value


def add_to_global(rs_name, field, amount):
    """Read-modify-write in one statement so two concurrent Dink events cannot
    lose an increment the way the JSON version could."""
    _check_global_field(field)
    with db.transaction():
        db.execute(
            f"UPDATE players SET {field} = {field} + ? WHERE rs_name = ?",
            (amount, rs_name))
        return db.scalar(f"SELECT {field} FROM players WHERE rs_name = ?", (rs_name,), 0)


def reset_global_all(field, value=0):
    _check_global_field(field)
    db.execute(f"UPDATE players SET {field} = ?", (value,))


def _check_global_field(field):
    if field not in _GLOBAL_FIELDS:
        raise ValueError(f"not a global player field: {field!r}")


# --------------------------------------------------------------------------- #
# Dink links
# --------------------------------------------------------------------------- #

def dink_key_in_use(key):
    return db.scalar(
        "SELECT 1 FROM players WHERE dink_link_key = ?", (key,)) is not None


def player_for_dink_key(key):
    return db.one("SELECT * FROM players WHERE dink_link_key = ?", (key,))


def set_dink_key(rs_name, key):
    ensure(rs_name)
    db.execute("UPDATE players SET dink_link_key = ? WHERE rs_name = ?", (key, rs_name))
    return key


# --------------------------------------------------------------------------- #
# Rename / delete
# --------------------------------------------------------------------------- #

def rename(old_rs_name, new_rs_name):
    """Rename in place, keeping the player id.

    The JSON version had to copy sotw_xp, botw_kills, the dinklink, every
    per-server entry and the whole stats blob across to new keys, and delete the
    old ones. Because history and links hang off the id here, none of that
    moves — which also means SOTW/BOTW history placements keep pointing at the
    same player instead of silently detaching.
    """
    db.execute("UPDATE players SET rs_name = ?, display_name = ? WHERE rs_name = ?",
               (new_rs_name, name_to_discord(new_rs_name), old_rs_name))


def merge_into(source_rs_name, target_rs_name):
    """Move everything the old identity accumulated onto the new one.

    A transfer means "this player is now known by the new name", so anything
    tied to the old name belongs to the new one. rename() achieves that for
    free by keeping the id, but it only works when the destination name is
    free. When the destination is already a player the operation is a merge,
    the id has to change, and every table keyed on the old id has to follow or
    the history is stranded on a row nobody can reach.

    What moves, and why:

      stat history        the account's past; without it a chart restarts at
                          the transfer
      events              feed continuity
      SOTW/BOTW placements  re-pointed by id, but player_name is left alone.
                          The name records who they were called at the time,
                          which is true and is what the standings fall back to
                          for deleted players; the id is what credits the
                          trophy to the right person now.
      dink_link_key       only if the destination has none, since overwriting a
                          working key would break that account's RuneLite
                          config silently.

    Current stats are NOT moved: the caller replaces them with a fresh fetch.

    Returns a dict of what moved, for logging. Caller supplies the transaction.
    """
    source_id = get_id(source_rs_name)
    target_id = get_id(target_rs_name)
    if source_id is None or target_id is None or source_id == target_id:
        return {}

    moved = {}
    for table in ("player_skill_history", "player_activity_history", "events",
                  "sotw_week_players", "botw_week_players"):
        cur = db.execute(f"UPDATE {table} SET player_id = ? WHERE player_id = ?",
                         (target_id, source_id))
        if cur.rowcount:
            moved[table] = cur.rowcount

    target_key = db.scalar("SELECT dink_link_key FROM players WHERE id = ?",
                           (target_id,))
    source_key = db.scalar("SELECT dink_link_key FROM players WHERE id = ?",
                           (source_id,))
    if source_key and not target_key:
        db.execute("UPDATE players SET dink_link_key = ? WHERE id = ?",
                   (source_key, target_id))
        moved["dink_link_key"] = 1
    if source_key:
        # The old row keeps no credential either way. Leaving a bearer token on
        # a retired identity serves nothing and the webhook routes on the
        # payload's player name, not on which row holds the key.
        db.execute("UPDATE players SET dink_link_key = NULL WHERE id = ?",
                   (source_id,))

    return moved


def delete(rs_name):
    """Remove the player entirely. Cascades to links and stats.

    SOTW/BOTW history placements survive with player_id set to NULL and
    player_name intact, so old standings still render.
    """
    db.execute("DELETE FROM players WHERE rs_name = ?", (rs_name,))


def untrack(rs_name):
    """Stop polling a player and drop their stats, without deleting the row.

    This is what "no more servers for this player" means: the old code deleted
    the db_runescape entry but kept sotw_xp and botw_kills in the discord file.
    """
    player_id = get_id(rs_name)
    if player_id is None:
        return
    with db.transaction():
        db.execute("DELETE FROM player_skill_current WHERE player_id = ?", (player_id,))
        db.execute("DELETE FROM player_activity_current WHERE player_id = ?", (player_id,))
        db.execute("UPDATE players SET tracked = 0 WHERE id = ?", (player_id,))

"""Discord servers (guilds) and their per-server settings."""

from . import db

# Interpolated into SQL by get_option/set_option, so restricted to a fixed set.
# The handlers forward a caller-supplied `entry` string from the admin commands.
_OPTION_FIELDS = ("sotw_opt", "sotw_progress", "botw_opt", "botw_progress")
_SETTING_FIELDS = ("channel_id", "role_id")

# The old handlers used JSON-key names; the admin cogs still pass those in.
_ALIASES = {"channel": "channel_id", "role": "role_id"}


def _resolve(field):
    field = _ALIASES.get(field, field)
    if field not in _OPTION_FIELDS + _SETTING_FIELDS:
        raise ValueError(f"not a server field: {field!r}")
    return field


def get(server_id):
    return db.one("SELECT * FROM servers WHERE id = ?", (server_id,))


def exists(server_id):
    return get(server_id) is not None


def add(server_id):
    """Add or re-activate a server.

    Re-adding keeps the previous settings and history, which is what the JSON
    version did by moving the id from removed_servers back to active_servers
    rather than rebuilding the entries.
    """
    existing = get(server_id)
    if existing is None:
        db.execute(
            "INSERT INTO servers (id, sotw_opt, sotw_progress, botw_opt,"
            " botw_progress, is_active) VALUES (?, 1, 1, 1, 1, 1)", (server_id,))
    else:
        db.execute(
            "UPDATE servers SET is_active = 1, removed_at = NULL WHERE id = ?",
            (server_id,))
    return True


def remove(server_id):
    """Deactivate, never delete — settings and SOTW/BOTW history are retained
    in case the bot is invited back."""
    db.execute("UPDATE servers SET is_active = 0, removed_at = ? WHERE id = ?",
               (db.utcnow(), server_id))
    return True


def sync_identity(server_id, name, icon_hash=None):
    """Record a guild's display name and icon hash. Called by the bot only.

    UPDATE, never INSERT. A row in `servers` means the guild ran setup, and the
    bot is typically in guilds that have not; creating rows here would invent
    servers the bot was never configured for and change what active_ids() and
    the looper see.

    Returns True if a row was actually updated.
    """
    cur = db.execute(
        "UPDATE servers SET name = ?, icon_hash = ? WHERE id = ?"
        # Skip the write when nothing moved. This runs on every on_ready, and a
        # no-op UPDATE would still dirty a page and wake the WAL for nothing.
        "  AND (name IS NOT ? OR icon_hash IS NOT ?)",
        (name, icon_hash, server_id, name, icon_hash))
    return cur.rowcount > 0


def identity(server_id):
    """{'name', 'icon_hash'} for a guild, both possibly None."""
    row = db.one("SELECT name, icon_hash FROM servers WHERE id = ?", (server_id,))
    return {"name": None, "icon_hash": None} if row is None else \
        {"name": row["name"], "icon_hash": row["icon_hash"]}


def active_ids():
    return [r["id"] for r in db.query(
        "SELECT id FROM servers WHERE is_active = 1 ORDER BY id")]


def get_option(server_id, field):
    """NULL means the JSON key was absent, which the old code read as True."""
    field = _resolve(field)
    default = 1 if field in _OPTION_FIELDS else None
    value = db.scalar(
        f"SELECT COALESCE({field}, ?) FROM servers WHERE id = ?",
        (default, server_id))
    if field in _OPTION_FIELDS:
        return bool(value) if value is not None else True
    return value


def set_option(server_id, field, value):
    field = _resolve(field)
    if field in _OPTION_FIELDS:
        value = int(bool(value))
    db.execute(f"UPDATE servers SET {field} = ? WHERE id = ?", (value, server_id))
    return value


def toggle_option(server_id, field):
    new_value = not get_option(server_id, field)
    set_option(server_id, field, new_value)
    return new_value


def info(server_id):
    """The {'id', 'channel', 'role'} dict the messaging helpers expect."""
    row = get(server_id)
    if row is None:
        return None
    return {"id": row["id"], "channel": row["channel_id"], "role": row["role_id"]}


def info_all(active_only=True):
    """Replaces LoopPlayerHandler.get_server_info_all().

    Keyed by str(server_id) because that is how the cogs index it — they do
    server_info_all[str(player_server['server'])].
    """
    sql = "SELECT id, channel_id, role_id FROM servers"
    if active_only:
        sql += " WHERE is_active = 1"
    return {str(r["id"]): {"channel": r["channel_id"], "role": r["role_id"]}
            for r in db.query(sql + " ORDER BY id")}


def list_active():
    """Replaces get_all_servers(): a list of {'id', 'channel', 'role'} dicts."""
    return [{"id": r["id"], "channel": r["channel_id"], "role": r["role_id"]}
            for r in db.query(
                "SELECT id, channel_id, role_id FROM servers"
                " WHERE is_active = 1 ORDER BY id")]


def list_for_competition(kind, progress_only=False):
    """Active servers opted into SOTW or BOTW. kind is 'sotw' or 'botw'."""
    if kind not in ("sotw", "botw"):
        raise ValueError(f"not a competition: {kind!r}")
    sql = (f"SELECT id, channel_id, role_id FROM servers"
           f" WHERE is_active = 1 AND COALESCE({kind}_opt, 1) = 1")
    if progress_only:
        sql += f" AND COALESCE({kind}_progress, 1) = 1"
    return [{"id": r["id"], "channel": r["channel_id"], "role": r["role_id"]}
            for r in db.query(sql + " ORDER BY id")]


def player_names(server_id):
    """Every player in a server — was server:<id>#all_players."""
    return [r["rs_name"] for r in db.query(
        "SELECT p.rs_name FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        " WHERE ps.server_id = ? ORDER BY p.rs_name", (server_id,))]


def members_players(server_id):
    """{str(member_id): [rs_name, ...]} — replaces get_server_players()."""
    out = {}
    for row in db.query(
            "SELECT ps.member_id, p.rs_name FROM player_servers ps"
            " JOIN players p ON p.id = ps.player_id"
            " WHERE ps.server_id = ? ORDER BY ps.member_id, p.rs_name", (server_id,)):
        out.setdefault(str(row["member_id"]), []).append(row["rs_name"])
    return out

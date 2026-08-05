"""Discord member identity: who owns an account.

Written by the bot, read by the web UI, which has no Discord connection and so
cannot resolve a member id into a name or an avatar on its own.

SCOPE IS DELIBERATELY NARROW. Only members that already appear in
player_servers are recorded, i.e. people who have put an account into the log.
Storing profile data about everyone in every guild the bot happens to be in
would serve nothing.

Avatar hashes are stored, not URLs. The URL is derivable from (id, hash), and
pinning one would bake in a CDN host that is Discord's to change.
"""

from . import db


def sync(member_id, username, display_name, avatar_hash=None):
    """Record or refresh one member. Called by the bot only.

    `display_name` is the caller's ACCOUNT-WIDE name for this member, not a
    per-server nickname: see the note in cogs/cmds/web.py:sync_member. It may
    be None, and readers fall back to `username`.

    Skips the write when nothing has changed: this runs for every linked member
    on every on_ready, and a no-op UPDATE would still dirty a page and wake the
    WAL for nothing.

    Returns True if a row was actually written.
    """
    existing = db.one(
        "SELECT username, display_name, avatar_hash FROM discord_members"
        " WHERE member_id = ?", (member_id,))
    if existing is not None and (existing["username"] == username
                                 and existing["display_name"] == display_name
                                 and existing["avatar_hash"] == avatar_hash):
        return False
    db.execute(
        "INSERT INTO discord_members (member_id, username, display_name,"
        " avatar_hash, updated_at) VALUES (?,?,?,?,?)"
        " ON CONFLICT(member_id) DO UPDATE SET"
        "   username = excluded.username, display_name = excluded.display_name,"
        "   avatar_hash = excluded.avatar_hash, updated_at = excluded.updated_at",
        (member_id, username, display_name, avatar_hash, db.utcnow()))
    return True


def linked_member_ids():
    """Every member id that owns a player in an active server.

    The list the bot syncs, and the boundary of what this table ever holds.
    """
    return [r["member_id"] for r in db.query(
        "SELECT DISTINCT ps.member_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE s.is_active = 1 AND ps.member_id IS NOT NULL")]


def get(member_id):
    """{'display_name', 'username', 'avatar_hash'} or None."""
    row = db.one(
        "SELECT username, display_name, avatar_hash FROM discord_members"
        " WHERE member_id = ?", (member_id,))
    if row is None:
        return None
    return {"username": row["username"],
            "display_name": row["display_name"],
            "avatar_hash": row["avatar_hash"]}


def owners_of(player_id):
    """The members who own a player, across the active servers it is in.

    A list rather than a single value: player_servers carries a member id per
    (player, server) row, so a transferred account can belong to different
    people in different servers.
    """
    return db.query(
        "SELECT DISTINCT ps.member_id, m.username, m.display_name, m.avatar_hash"
        " FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " LEFT JOIN discord_members m ON m.member_id = ps.member_id"
        " WHERE ps.player_id = ? AND s.is_active = 1 AND ps.member_id IS NOT NULL"
        " ORDER BY ps.member_id", (player_id,))


def prune_unlinked():
    """Drop rows for members who no longer own anything.

    Not called automatically. It exists so that leaving the log can be made to
    remove the profile data too, rather than leaving it to sit indefinitely.
    """
    cur = db.execute(
        "DELETE FROM discord_members WHERE member_id NOT IN ("
        "  SELECT DISTINCT ps.member_id FROM player_servers ps"
        "  JOIN servers s ON s.id = ps.server_id"
        "  WHERE s.is_active = 1 AND ps.member_id IS NOT NULL)")
    return cur.rowcount

"""Every SQL statement the web UI runs.

WHY THIS IS NOT IN data/repo/
-----------------------------
data/repo/ is the bot's package. Keeping UI queries out of it preserves a rule
that is worth having on a droplet where one checkout serves two services:

    a pull that changes only web/ can never require a bot restart

and that rule is mechanically checkable with `git diff --stat -- osrs-event-log/`.
The repo layer is still reused for what it already does well (connection
handling, competitions, credentials); what lives here is the reshaping the bot
has no use for: leaderboards, feeds, aggregates and the visibility filter.

THE PERMISSION BOUNDARY
-----------------------
Almost every function takes `player_ids`, a list produced by
visible_player_ids(). That list is derived from the signed-in member's servers
on every request and is never cached in the session cookie. Functions that take
it will return nothing for an empty list rather than everything, which is the
safe direction to fail in: a bug that loses the member's servers shows an empty
site, not everyone else's data.

NEVER SELECTED HERE
-------------------
players.dink_link_key       plaintext bearer tokens for the public webhook
player_servers.member_id    real Discord user ids
events.payload              raw Dink bodies, which carry dinkAccountHash

Columns are enumerated in every statement for that reason. `SELECT *` is banned
in this file, including through repo helpers: repo.players.get() does
`SELECT *` and hands back the Dink key, so the UI must not call it.
web/tests/test_privacy.py enforces all of this against real rendered pages.
"""

from . import config  # noqa: F401  (sys.path)

from flask import g  # noqa: E402

from data import repo  # noqa: E402

# Guard against a stray SELECT * creeping in later. Cheap, and the failure it
# prevents is publishing bearer tokens.
_FORBIDDEN_COLUMNS = ("dink_link_key", "member_id", "payload")


def _placeholders(values):
    return ",".join("?" * len(values))


# --------------------------------------------------------------------------- #
# Visibility
# --------------------------------------------------------------------------- #

# The access rule itself lives in data/repo/webauth.py, next to the rest of it
# (visible_server_ids, own_player_names). A permission boundary split across two
# packages is one nobody can read in one sitting, and keeping it there lets the
# bot's own test suite exercise it without importing Flask.
visible_player_ids = repo.webauth.visible_player_ids


def narrow_to_server(player_ids, server_id):
    """The subset of an already-visible set that is in one server.

    Takes the caller's visible list rather than querying the server directly, so
    narrowing can only ever remove players. A server filter must not be able to
    widen what someone can see, even if the server id were wrong.
    """
    if not player_ids:
        return []
    in_server = {r["player_id"] for r in repo.db.query(
        "SELECT DISTINCT player_id FROM player_servers WHERE server_id = ?",
        (server_id,))}
    return [pid for pid in player_ids if pid in in_server]


def server_label(server_id, names, ordinal):
    """A display name for a guild.

    Best available first:

      1. SERVER_NAMES, so a friendlier label than the real guild name can be
         set without touching the database
      2. servers.name, which the bot keeps in step, so a new or renamed server
         needs no configuration at all
      3. an ordinal

    Never the raw snowflake. Guild ids are semi-private and this repo is public,
    so a label is always either chosen or fetched by the bot.
    """
    override = names.get(server_id)
    if override:
        return override
    return _identity(server_id)["name"] or f"Server {ordinal}"


def _identity(server_id):
    """Guild name and icon hash, cached for the life of the request.

    Read repeatedly while rendering a page (nav, tabs, per player). It is a
    handful of rows that cannot change mid-request, so caching beats
    re-querying on every label.
    """
    cache = getattr(g, "_server_identity", None)
    if cache is None:
        cache = g._server_identity = {}
    if server_id not in cache:
        cache[server_id] = repo.servers.identity(server_id)
    return cache[server_id]


def server_icon_url(server_id, size=64):
    """Discord CDN URL for a guild's icon, or None.

    Built from (id, hash) rather than stored, so the CDN host stays Discord's to
    change. An 'a_' prefix means an animated icon, served as .gif; anything else
    is .png.

    This is the only external request the site makes. It is emitted on
    authenticated pages only, to a member of that guild, and Referrer-Policy is
    same-origin so no page path reaches Discord.
    """
    icon_hash = _identity(server_id)["icon_hash"]
    if not icon_hash:
        return None
    extension = "gif" if str(icon_hash).startswith("a_") else "png"
    return (f"https://cdn.discordapp.com/icons/{server_id}/{icon_hash}"
            f".{extension}?size={size}")


def server_view(server_id, names, ordinal):
    label = server_label(server_id, names, ordinal)
    named = label != f"Server {ordinal}"
    return {
        "id": server_id,
        "label": label,
        "icon": server_icon_url(server_id),
        # Shown instead of an icon when there is none. An initial is only
        # useful once a server has a real name: before the bot has filled
        # these in, every label is "Server N" and every initial would be a
        # useless "S". Fall back to the ordinal instead, which at least tells
        # the badges apart.
        "monogram": label[:1].upper() if named else str(ordinal),
    }


def visible_servers(member_id, names):
    """The member's active servers, in a stable order."""
    ids = repo.webauth.visible_server_ids(member_id)
    all_active = repo.servers.active_ids()
    return [server_view(sid, names, all_active.index(sid) + 1) for sid in ids]


# --------------------------------------------------------------------------- #
# Anonymous aggregates: counts only, no names, ever
# --------------------------------------------------------------------------- #

def public_summary():
    """What a signed-out visitor sees. Deliberately contains no player names,
    no server names and no ids, so nothing here identifies a real person."""
    scalar = repo.db.scalar
    overall = ("(SELECT id FROM skills WHERE name = 'Overall')")

    return {
        "players_tracked": scalar(
            "SELECT COUNT(*) FROM pollable_players", (), 0),
        "players_total": scalar("SELECT COUNT(*) FROM players", (), 0),
        "servers_active": scalar(
            "SELECT COUNT(*) FROM servers WHERE is_active = 1", (), 0),
        "total_xp": scalar(
            f"SELECT SUM(xp) FROM player_skill_current WHERE skill_id = {overall}",
            (), 0) or 0,
        "total_levels": scalar(
            f"SELECT SUM(level) FROM player_skill_current WHERE skill_id = {overall}",
            (), 0) or 0,
        "skills_tracked": scalar("SELECT COUNT(*) FROM skills", (), 0),
        "activities_tracked": scalar("SELECT COUNT(*) FROM activities", (), 0),
        "events_total": scalar("SELECT COUNT(*) FROM events", (), 0),
        "events_recent": scalar(
            "SELECT COUNT(*) FROM events WHERE occurred_at >= ?",
            (_days_ago(7),), 0),
        "last_poll": scalar("SELECT MAX(last_polled) FROM players"),
        "history_since": scalar("SELECT MIN(recorded_at) FROM player_skill_history"),
        "history_rows": scalar(
            "SELECT COUNT(*) FROM player_skill_history", (), 0)
        + scalar("SELECT COUNT(*) FROM player_activity_history", (), 0),
        "weeks_recorded": scalar("SELECT COUNT(*) FROM sotw_weeks", (), 0)
        + scalar("SELECT COUNT(*) FROM botw_weeks", (), 0),
        "current_skill": _config_value("sotw", "current_skill"),
        "current_boss": _config_value("botw", "current_boss"),
    }


def _config_value(kind, key):
    try:
        return repo.competitions.get_config(kind).get(key)
    except Exception:
        return None


def _days_ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Players
# --------------------------------------------------------------------------- #

_PLAYER_COLUMNS = """
    p.id, p.rs_name, p.display_name, p.tracked, p.last_polled,
    p.sotw_xp, p.botw_kills
"""

# Total level and Overall XP come from the 'Overall' hiscores row. A player who
# has dropped off the hiscores has no Overall row at all (see project-notes:
# the old page omitted skills with no xp), so both fall back to summing the
# skills that do exist. Without the fallback those players render as level 0.
_OVERALL_JOIN = """
    LEFT JOIN player_skill_current o
           ON o.player_id = p.id
          AND o.skill_id = (SELECT id FROM skills WHERE name = 'Overall')
"""

_TOTALS = """
    COALESCE(o.level, (SELECT SUM(c.level) FROM player_skill_current c
                       JOIN skills sk ON sk.id = c.skill_id
                       WHERE c.player_id = p.id AND sk.name <> 'Overall')) AS total_level,
    COALESCE(o.xp,    (SELECT SUM(c.xp) FROM player_skill_current c
                       JOIN skills sk ON sk.id = c.skill_id
                       WHERE c.player_id = p.id AND sk.name <> 'Overall')) AS total_xp,
    o.rank AS overall_rank,
    (SELECT COUNT(*) FROM player_skill_current c WHERE c.player_id = p.id) AS skill_rows,
    (SELECT COUNT(*) FROM player_activity_current c WHERE c.player_id = p.id) AS activity_rows
"""


def players_index(player_ids):
    """One row per visible player. One query, no N+1."""
    if not player_ids:
        return []
    return repo.db.query(
        f"SELECT {_PLAYER_COLUMNS}, {_TOTALS}"
        f" FROM players p {_OVERALL_JOIN}"
        f" WHERE p.id IN ({_placeholders(player_ids)})"
        " ORDER BY total_level DESC, total_xp DESC, p.rs_name",
        player_ids)


def player_by_name(rs_name, player_ids):
    """A single player, but only if they are inside the caller's visible set.

    The visibility check is part of the query rather than a separate `if`, so
    there is no code path that fetches the row first and forgets to check.
    """
    if not player_ids:
        return None
    return repo.db.one(
        f"SELECT {_PLAYER_COLUMNS}, {_TOTALS}"
        f" FROM players p {_OVERALL_JOIN}"
        f" WHERE p.rs_name = ? AND p.id IN ({_placeholders(player_ids)})",
        [rs_name] + list(player_ids))


def player_skills(player_id):
    """Current skills in hiscores order. sort_order is populated for all 25."""
    return repo.db.query(
        "SELECT sk.name, sk.sort_order, c.level, c.xp, c.rank, c.updated_at"
        " FROM player_skill_current c JOIN skills sk ON sk.id = c.skill_id"
        " WHERE c.player_id = ? ORDER BY sk.sort_order, sk.name", (player_id,))


def player_activities(player_id):
    """Current minigames/bosses. Only what the player has actually done: the
    bot stores a row only for score > 0."""
    return repo.db.query(
        "SELECT a.name, a.sort_order, c.score, c.rank, c.updated_at"
        " FROM player_activity_current c JOIN activities a ON a.id = c.activity_id"
        " WHERE c.player_id = ? ORDER BY a.sort_order, a.name", (player_id,))


def player_server_labels(player_id, names):
    """Which servers a player appears in. Ids are mapped to labels and the
    member_id column on these rows is never read."""
    all_active = repo.servers.active_ids()
    rows = repo.db.query(
        "SELECT ps.server_id, s.is_active FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.player_id = ? ORDER BY ps.server_id", (player_id,))
    out = []
    for row in rows:
        sid = row["server_id"]
        if sid in all_active:
            view = server_view(sid, names, all_active.index(sid) + 1)
        else:
            # The bot was removed from this guild, so there is nothing current
            # to name it by and its stored name may be stale.
            view = {"id": sid, "label": "a server the bot has left",
                    "icon": None, "monogram": "?"}
        view["is_active"] = bool(row["is_active"])
        out.append(view)
    return out


# --------------------------------------------------------------------------- #
# Discord member identity
# --------------------------------------------------------------------------- #
# THE ONE SANCTIONED EXCEPTION TO "member_id NEVER LEAVES THE DATABASE".
#
# A Discord avatar lives at cdn.discordapp.com/avatars/<user_id>/<hash>, so the
# user id is unavoidably in the URL and therefore in the page. Dylan accepted
# that trade deliberately: the page is only ever served to someone who shares a
# Discord server with that member, and they can already read the same id in
# Discord with developer mode on.
#
# The rule is narrowed, not dropped. A member id may appear ONLY inside an
# avatar URL. web/tests/test_privacy.py still fails on an id anywhere else, so
# it keeps its teeth.

def member_avatar_url(member_id, avatar_hash, size=64):
    """Discord CDN URL for a member's avatar, or None for the monogram."""
    if not avatar_hash:
        return None
    extension = "gif" if str(avatar_hash).startswith("a_") else "png"
    return (f"https://cdn.discordapp.com/avatars/{member_id}/{avatar_hash}"
            f".{extension}?size={size}")


def member_view(row):
    """{'name', 'avatar', 'monogram'} from a discord_members row.

    A member the bot has not recorded yet renders as "Unknown" with a neutral
    monogram rather than exposing the raw id as a label.
    """
    name = (row["display_name"] or row["username"] or "Unknown") \
        if row is not None else "Unknown"
    avatar_hash = row["avatar_hash"] if row is not None else None
    return {
        "name": name,
        "avatar": member_avatar_url(row["member_id"], avatar_hash)
        if row is not None else None,
        "monogram": name[:1].upper(),
    }


def player_owners(player_id):
    """Who owns a player, as view dicts. Usually one."""
    return [member_view(row) for row in repo.members.owners_of(player_id)]


def my_identity(member_id):
    """The signed-in member's own name and avatar."""
    row = repo.members.get(member_id)
    if row is None:
        return member_view(None)
    return member_view({"member_id": member_id, **row})


# --------------------------------------------------------------------------- #
# The signed-in member's own accounts
# --------------------------------------------------------------------------- #

def own_accounts(member_id):
    """Full rows for the accounts this member owns, richest first.

    Ownership is a per-server property: a player links to a server WITH a
    member id, so an account transferred to someone else in another server is
    not wholly "yours". This asks for players where at least one active-server
    link names this member, which is the same set ;myaccounts would list.
    """
    return repo.db.query(
        f"SELECT {_PLAYER_COLUMNS}, {_TOTALS},"
        # A boolean, never the key itself. Whether Dink is set up is genuinely
        # useful to see; the token is a bearer credential for a public endpoint
        # and must not leave the database.
        "  (p.dink_link_key IS NOT NULL) AS dink_configured,"
        "  (SELECT COUNT(*) FROM events e WHERE e.player_id = p.id) AS event_count"
        f" FROM players p {_OVERALL_JOIN}"
        " WHERE p.id IN (SELECT ps.player_id FROM player_servers ps"
        "                JOIN servers s ON s.id = ps.server_id"
        "                WHERE ps.member_id = ? AND s.is_active = 1)"
        " ORDER BY total_level DESC, total_xp DESC, p.rs_name",
        (member_id,))


def own_account_links(player_id, member_id, names):
    """Per-server settings for one of the member's accounts.

    member_id is a filter here and is never returned or rendered. NULL columns
    mean the JSON key was absent, which the bot reads as True, so they are
    COALESCEd the same way every read path does.
    """
    all_active = repo.servers.active_ids()
    rows = repo.db.query(
        "SELECT ps.server_id, s.is_active,"
        " COALESCE(ps.mention, 1)  AS mention,"
        " COALESCE(ps.sotw_opt, 1) AS sotw_opt,"
        " COALESCE(ps.botw_opt, 1) AS botw_opt"
        " FROM player_servers ps JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.player_id = ? AND ps.member_id = ?"
        " ORDER BY s.is_active DESC, ps.server_id", (player_id, member_id))
    out = []
    for row in rows:
        sid = row["server_id"]
        if sid in all_active:
            view = server_view(sid, names, all_active.index(sid) + 1)
        else:
            view = {"id": sid, "label": "a server the bot has left",
                    "icon": None, "monogram": "?"}
        view.update({
            "is_active": bool(row["is_active"]),
            "mention": bool(row["mention"]),
            "sotw_opt": bool(row["sotw_opt"]),
            "botw_opt": bool(row["botw_opt"]),
        })
        out.append(view)
    return out


def other_owner_servers(player_id, member_id):
    """How many servers hold this account under a DIFFERENT member.

    Rare, but real: player_servers is keyed on (player, server) and carries a
    member id per row, so a transferred account can be linked to someone else
    elsewhere. Worth surfacing as a count rather than pretending the account is
    entirely yours.
    """
    return repo.db.scalar(
        "SELECT COUNT(*) FROM player_servers ps JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.player_id = ? AND s.is_active = 1"
        "   AND (ps.member_id IS NULL OR ps.member_id <> ?)",
        (player_id, member_id), 0)


def podium_count(player_id, rs_name, kind):
    conf = comp(kind)
    return repo.db.scalar(
        f"SELECT COUNT(*) FROM {conf['players']} wp"
        f" JOIN {conf['weeks']} w ON w.id = wp.week_id"
        " WHERE wp.player_id = ? OR wp.player_name = ?",
        (player_id, rs_name), 0)


def credential_info(member_id):
    """When this member's own web password was issued, and how many times.

    Their own metadata, and never the hash. Lets the page answer "is the
    password I am holding still the current one" without exposing anything.
    """
    row = repo.db.one(
        "SELECT issued_at, issued_count FROM web_credentials WHERE member_id = ?",
        (member_id,))
    return {"issued_at": row["issued_at"], "issued_count": row["issued_count"]} \
        if row else None


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

def skill_history(player_id, skill_name, limit=2000):
    return repo.db.query(
        "SELECT h.level, h.xp, h.rank, h.recorded_at"
        " FROM player_skill_history h JOIN skills sk ON sk.id = h.skill_id"
        " WHERE h.player_id = ? AND sk.name = ?"
        " ORDER BY h.recorded_at LIMIT ?", (player_id, skill_name, limit))


def activity_history(player_id, activity_name, limit=2000):
    return repo.db.query(
        "SELECT h.score, h.rank, h.recorded_at"
        " FROM player_activity_history h JOIN activities a ON a.id = h.activity_id"
        " WHERE h.player_id = ? AND a.name = ?"
        " ORDER BY h.recorded_at LIMIT ?", (player_id, activity_name, limit))


def history_depth(player_id):
    """How much history exists for a player, so a page can say so honestly
    instead of drawing a chart from one point.

    History only started at the migration and only grows when a value actually
    changes, so for most players this is 1 for a long time.
    """
    return {
        "points": repo.db.scalar(
            "SELECT COUNT(DISTINCT recorded_at) FROM player_skill_history"
            " WHERE player_id = ?", (player_id,), 0),
        "since": repo.db.scalar(
            "SELECT MIN(recorded_at) FROM player_skill_history"
            " WHERE player_id = ?", (player_id,)),
        "latest": repo.db.scalar(
            "SELECT MAX(recorded_at) FROM player_skill_history"
            " WHERE player_id = ?", (player_id,)),
    }


def skills_with_movement(player_id):
    """Skills that have more than one recorded value, i.e. the ones whose chart
    would show anything. Used to default the chart to something worth looking
    at rather than to Attack."""
    return [r["name"] for r in repo.db.query(
        "SELECT sk.name, COUNT(DISTINCT h.recorded_at) n"
        " FROM player_skill_history h JOIN skills sk ON sk.id = h.skill_id"
        " WHERE h.player_id = ? GROUP BY sk.name HAVING n > 1"
        " ORDER BY n DESC, sk.sort_order", (player_id,))]


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
# NOTE: events.server_id is NULL for every row the bot writes today. Both call
# sites (LoopPlayerHandler.record_events and the Dink webhook) pass None,
# because the message text is identical across servers and which servers saw it
# is derivable from player_servers. So the feed filters by PLAYER, not by
# server. Filtering on e.server_id would silently return nothing.

def events_feed(player_ids, limit=50, offset=0, source=None, event_type=None,
                player_id=None):
    """The activity feed, restricted to visible players.

    `payload` is never selected. It holds the raw Dink body, which carries
    dinkAccountHash and whatever else the plugin sent.
    """
    if not player_ids:
        return []
    ids = list(player_ids)
    if player_id is not None:
        if player_id not in player_ids:
            return []
        ids = [player_id]

    sql = ("SELECT e.id, e.source, e.event_type, e.title, e.message,"
           " e.occurred_at, e.posted, p.rs_name, p.display_name"
           " FROM events e JOIN players p ON p.id = e.player_id"
           f" WHERE e.player_id IN ({_placeholders(ids)})")
    params = list(ids)
    if source:
        sql += " AND e.source = ?"
        params.append(source)
    if event_type:
        sql += " AND e.event_type = ?"
        params.append(event_type)
    return repo.db.query(
        sql + " ORDER BY e.occurred_at DESC, e.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset])


def events_count(player_ids, source=None, event_type=None, player_id=None):
    if not player_ids:
        return 0
    ids = [player_id] if player_id is not None and player_id in player_ids \
        else list(player_ids)
    sql = ("SELECT COUNT(*) FROM events e"
           f" WHERE e.player_id IN ({_placeholders(ids)})")
    params = list(ids)
    if source:
        sql += " AND e.source = ?"
        params.append(source)
    if event_type:
        sql += " AND e.event_type = ?"
        params.append(event_type)
    return repo.db.scalar(sql, params, 0)


def event_types(player_ids):
    """Distinct (source, type) pairs present, for building the filter menu.
    Built from the data rather than hardcoded, because Dink adds event types."""
    if not player_ids:
        return []
    return repo.db.query(
        "SELECT e.source, e.event_type, COUNT(*) AS n FROM events e"
        f" WHERE e.player_id IN ({_placeholders(player_ids)})"
        " GROUP BY e.source, e.event_type ORDER BY n DESC", list(player_ids))


# --------------------------------------------------------------------------- #
# SOTW / BOTW
# --------------------------------------------------------------------------- #

_COMP = {
    "sotw": {"weeks": "sotw_weeks", "players": "sotw_week_players",
             "name_col": "skill_name", "score_col": "xp",
             "live_col": "sotw_xp", "opt_col": "sotw_opt",
             "label": "Skill of the Week", "noun": "skill"},
    "botw": {"weeks": "botw_weeks", "players": "botw_week_players",
             "name_col": "boss_name", "score_col": "kills",
             "live_col": "botw_kills", "opt_col": "botw_opt",
             "label": "Boss of the Week", "noun": "boss"},
}


def comp(kind):
    if kind not in _COMP:
        raise ValueError(f"not a competition: {kind!r}")
    return _COMP[kind]


def live_standings(server_id, kind, limit=25):
    """The week in progress. Mirrors repo.competitions.top_players() but keeps
    the player id so the UI can link, and respects the per-player opt-out."""
    conf = comp(kind)
    return repo.db.query(
        f"SELECT p.id, p.rs_name, p.display_name, p.{conf['live_col']} AS score"
        " FROM player_servers ps JOIN players p ON p.id = ps.player_id"
        f" WHERE ps.server_id = ? AND p.{conf['live_col']} > 0"
        f"   AND COALESCE(ps.{conf['opt_col']}, 1) = 1"
        f" ORDER BY p.{conf['live_col']} DESC, p.rs_name LIMIT ?",
        (server_id, limit))


def all_time_standings(server_id, kind, limit=50):
    """Trophy totals.

    Deliberately NOT v_sotw_standings / v_botw_standings. Those views group by
    player_name, which splits a renamed player's trophies across two rows: a
    rename keeps the player id (see rename() in data/repo/players.py) but old
    placements still carry the old name. Grouping by the id where there is one
    and falling back to the name where there is not keeps a renamed player
    whole, while still counting players who have since been deleted entirely
    (76 of 1158 SOTW placements have a NULL player_id).
    """
    conf = comp(kind)
    return repo.db.query(
        f"""
        SELECT COALESCE(CAST(wp.player_id AS TEXT), 'name:' || wp.player_name) AS grp,
               MAX(p.rs_name)      AS rs_name,
               MAX(wp.player_name) AS fallback_name,
               MAX(p.id)           AS player_id,
               COUNT(*)                                       AS weeks_placed,
               SUM(wp.{conf['score_col']})                    AS total,
               SUM(CASE WHEN wp.rank = 1 THEN 1 ELSE 0 END)   AS rank_1,
               SUM(CASE WHEN wp.rank = 2 THEN 1 ELSE 0 END)   AS rank_2,
               SUM(CASE WHEN wp.rank = 3 THEN 1 ELSE 0 END)   AS rank_3,
               SUM(CASE wp.rank WHEN 1 THEN 3 WHEN 2 THEN 2 WHEN 3 THEN 1
                                ELSE 0 END)                   AS rank_weight
        FROM {conf['players']} wp
        JOIN {conf['weeks']} w ON w.id = wp.week_id
        LEFT JOIN players p ON p.id = wp.player_id
        WHERE w.server_id = ?
        GROUP BY grp
        ORDER BY rank_weight DESC, total DESC, rs_name, fallback_name
        LIMIT ?
        """, (server_id, limit))


def past_weeks(server_id, kind, limit=40, offset=0):
    """Completed weeks, newest first.

    Many weeks have no placements at all (138 of 212 BOTW weeks, 83 of 525
    SOTW), so the podium list is frequently empty and the template must say so
    rather than render a blank row.
    """
    conf = comp(kind)
    weeks = repo.db.query(
        f"SELECT w.id, w.{conf['name_col']} AS name, w.ended_on, w.seq"
        f" FROM {conf['weeks']} w WHERE w.server_id = ?"
        " ORDER BY w.seq DESC LIMIT ? OFFSET ?", (server_id, limit, offset))
    if not weeks:
        return []
    week_ids = [w["id"] for w in weeks]
    podium = {}
    for row in repo.db.query(
            f"SELECT wp.week_id, wp.player_name, wp.player_id, wp.rank,"
            f" wp.{conf['score_col']} AS score, p.rs_name, p.display_name"
            f" FROM {conf['players']} wp"
            " LEFT JOIN players p ON p.id = wp.player_id"
            f" WHERE wp.week_id IN ({_placeholders(week_ids)})"
            " ORDER BY wp.week_id, wp.seq", week_ids):
        podium.setdefault(row["week_id"], []).append(row)
    return [{"week": w, "podium": podium.get(w["id"], [])} for w in weeks]


def weeks_count(server_id, kind):
    conf = comp(kind)
    return repo.db.scalar(
        f"SELECT COUNT(*) FROM {conf['weeks']} WHERE server_id = ?",
        (server_id,), 0)


def player_podiums(player_id, rs_name, kind, server_ids):
    """A player's placements.

    Matched on `player_id OR player_name` because a rename keeps the id while
    older placements still carry the old name, and because placements for
    deleted players keep only the name. Restricted to the caller's servers so a
    podium cannot leak a competition from a server they are not in.
    """
    conf = comp(kind)
    if not server_ids:
        return []
    return repo.db.query(
        f"SELECT w.{conf['name_col']} AS name, w.ended_on, wp.rank,"
        f" wp.{conf['score_col']} AS score, w.server_id"
        f" FROM {conf['players']} wp JOIN {conf['weeks']} w ON w.id = wp.week_id"
        " WHERE (wp.player_id = ? OR wp.player_name = ?)"
        f"   AND w.server_id IN ({_placeholders(server_ids)})"
        " ORDER BY w.ended_on DESC, w.seq DESC",
        [player_id, rs_name] + list(server_ids))


# --------------------------------------------------------------------------- #
# Leaderboards
# --------------------------------------------------------------------------- #

def skill_names():
    return [r["name"] for r in repo.db.query(
        "SELECT name FROM skills ORDER BY sort_order, name")]


def activity_names():
    """Only activities somebody actually has a score in, so the picker is not
    87 entries of which most are empty."""
    return [r["name"] for r in repo.db.query(
        "SELECT a.name FROM activities a"
        " WHERE EXISTS (SELECT 1 FROM player_activity_current c"
        "               WHERE c.activity_id = a.id)"
        " ORDER BY a.sort_order, a.name")]


def skill_leaderboard(player_ids, skill_name, limit=25):
    if not player_ids:
        return []
    return repo.db.query(
        "SELECT p.id, p.rs_name, p.display_name, c.level, c.xp, c.rank"
        " FROM player_skill_current c"
        " JOIN players p ON p.id = c.player_id"
        " JOIN skills sk ON sk.id = c.skill_id"
        f" WHERE sk.name = ? AND p.id IN ({_placeholders(player_ids)})"
        " ORDER BY c.xp DESC, p.rs_name LIMIT ?",
        [skill_name] + list(player_ids) + [limit])


def activity_leaderboard(player_ids, activity_name, limit=25):
    if not player_ids:
        return []
    return repo.db.query(
        "SELECT p.id, p.rs_name, p.display_name, c.score, c.rank"
        " FROM player_activity_current c"
        " JOIN players p ON p.id = c.player_id"
        " JOIN activities a ON a.id = c.activity_id"
        f" WHERE a.name = ? AND p.id IN ({_placeholders(player_ids)})"
        " ORDER BY c.score DESC, p.rs_name LIMIT ?",
        [activity_name] + list(player_ids) + [limit])

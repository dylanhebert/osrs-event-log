"""The event feed.

New with SQLite — nothing populated this before. Dink events in particular were
formatted, posted to Discord and discarded, so drops, pets, quests, clues and
collection log entries left no record at all. Recording them is what lets the
future web UI show an activity feed rather than only hiscores milestones.

`posted = 0` marks a Discord send that failed. Today that is only a log line, so
there is no way to find out afterwards what a server missed.

Recording is best-effort by design: log_event() must never be the reason a
message fails to post. Callers wrap it accordingly.
"""

import json

from . import db

SOURCE_HISCORES = "hiscores"
SOURCE_DINK = "dink"


def log_event(player_id, server_id, source, event_type, message,
              title=None, payload=None, posted=True, occurred_at=None,
              is_milestone=False):
    """Record one event.

    `is_milestone` is whether this was notable enough to ping the server's
    role, which is a different question from event_type: a pet drop is a PET
    event AND a milestone. Both sources produce them, hiscores through the
    milestone bucket and Dink through a formatter returning notify=True.
    """
    cur = db.execute(
        "INSERT INTO events (player_id, server_id, source, event_type, title,"
        " message, payload, occurred_at, posted, is_milestone)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (player_id, server_id, source, event_type, title, message,
         json.dumps(payload) if payload is not None else None,
         occurred_at or db.utcnow(), 1 if posted else 0,
         1 if is_milestone else 0))
    return cur.lastrowid


def mark_posted(event_id, posted=True):
    db.execute("UPDATE events SET posted = ? WHERE id = ?",
               (1 if posted else 0, event_id))


def recent(limit=50, server_id=None, player_id=None, source=None):
    sql = ("SELECT e.*, p.rs_name, p.display_name FROM events e"
           " LEFT JOIN players p ON p.id = e.player_id WHERE 1 = 1")
    params = []
    if server_id is not None:
        sql += " AND e.server_id = ?"
        params.append(server_id)
    if player_id is not None:
        sql += " AND e.player_id = ?"
        params.append(player_id)
    if source is not None:
        sql += " AND e.source = ?"
        params.append(source)
    return db.query(sql + " ORDER BY e.occurred_at DESC, e.id DESC LIMIT ?",
                    params + [limit])


def failed(limit=100):
    """Events that were recorded but never made it to Discord."""
    return db.query(
        "SELECT e.*, p.rs_name FROM events e LEFT JOIN players p ON p.id = e.player_id"
        " WHERE e.posted = 0 ORDER BY e.occurred_at DESC LIMIT ?", (limit,))

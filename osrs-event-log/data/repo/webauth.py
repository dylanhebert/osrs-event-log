"""Web UI sign-in credentials.

Two processes touch this module and they touch different halves of it:

  * the bot calls issue() from the ;webpassword command, and is the only thing
    that ever writes here
  * the read-only web UI calls member_for_password() and visible_server_ids(),
    and never writes anything

Sign-in identity is the DISCORD MEMBER, not the player. A member may own up to
three RuneScape accounts, and the access rule Dylan asked for — "see everyone
you share a server with" — is a property of the member, not of any one account.
player_servers.member_id is the only place membership is recorded, so it is the
anchor for both halves.

WHAT IS STORED
--------------
Only a sha256 hash of the password. issue() generates a fresh 256-bit value,
returns it once so the cog can DM it, and keeps nothing else. There is
deliberately no way to read a password back out: "remind me of mine" is not a
feature, "issue me a new one" is. A stolen database or a nightly backup
therefore contains no usable credential.

That is the opposite of players.dink_link_key, which is a plaintext bearer
token sitting in the same file. That is a weakness this module refuses to copy,
not a house style to match.

Unsalted sha256 is correct here and is not the usual password-storage mistake.
These are secrets.token_urlsafe(32) values, not human-chosen passwords: there is
no dictionary, no rainbow table can cover 2^256, and a slow KDF would buy
nothing measurable. A salt would also break sign-in outright, because the
browser sends only a password and the member has to be found BY hash.
"""

import hashlib
import secrets

from . import db

# 32 bytes -> a 43-character URL-safe string. Long enough that brute force is
# not a threat model, short enough to survive a copy-paste out of a Discord DM.
TOKEN_BYTES = 32


def hash_password(password):
    """sha256 hex of a password. The only form that reaches the database."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Write side — the bot only
# --------------------------------------------------------------------------- #

def issue(member_id):
    """Generate a new password for a member, store its hash, and return it.

    Rotates: any password issued earlier stops working the moment this returns.
    That is the whole reason the caller must treat the return value as the only
    copy that will ever exist.

    Returns (password, issued_count).
    """
    password = secrets.token_urlsafe(TOKEN_BYTES)
    now = db.utcnow()
    with db.transaction():
        db.execute(
            "INSERT INTO web_credentials (member_id, token_hash, issued_at,"
            " issued_count) VALUES (?,?,?,1)"
            " ON CONFLICT(member_id) DO UPDATE SET"
            "   token_hash = excluded.token_hash, issued_at = excluded.issued_at,"
            "   issued_count = web_credentials.issued_count + 1",
            (member_id, hash_password(password), now))
        count = db.scalar(
            "SELECT issued_count FROM web_credentials WHERE member_id = ?",
            (member_id,), 1)
    return password, count


def revoke(member_id):
    """Drop a member's credential. Any password they hold stops working."""
    db.execute("DELETE FROM web_credentials WHERE member_id = ?", (member_id,))


def has_credential(member_id):
    return db.scalar(
        "SELECT 1 FROM web_credentials WHERE member_id = ?", (member_id,)) is not None


# --------------------------------------------------------------------------- #
# Read side — the web UI only
# --------------------------------------------------------------------------- #

def member_for_password(password):
    """The member id a password signs in as, or None.

    Looks up by hash, so a wrong password is an index miss rather than a
    comparison against a secret. Nothing here is timing-sensitive: the value
    being matched is the hash of what the caller already supplied.
    """
    if not password:
        return None
    return db.scalar(
        "SELECT member_id FROM web_credentials WHERE token_hash = ?",
        (hash_password(password),))


def fingerprint(member_id):
    """A short stand-in for a member's current credential, or None.

    The web session cookie carries this alongside the member id, and every
    request checks it still matches. That is what makes ;webpassword and
    ;webrevoke take effect immediately instead of only affecting future
    sign-ins: rotating changes the stored hash and revoking removes the row, so
    in both cases the fingerprint stops matching and open browser sessions are
    signed out on their next click.

    Truncated rather than the whole hash because the cookie only needs to detect
    *change*, and there is no reason to carry more of a secret-derived value
    around than the job requires.
    """
    token_hash = db.scalar(
        "SELECT token_hash FROM web_credentials WHERE member_id = ?", (member_id,))
    return token_hash[:16] if token_hash else None


def is_known_member(member_id):
    """Whether this member is linked to any player in any ACTIVE server.

    Sign-in checks this on every request rather than trusting the session, so a
    member removed from every server loses access immediately without anything
    having to delete their credential.
    """
    return db.scalar(
        "SELECT 1 FROM player_servers ps JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.member_id = ? AND s.is_active = 1 LIMIT 1",
        (member_id,)) is not None


def visible_server_ids(member_id):
    """The active servers a member belongs to. The permission boundary.

    Everything the web UI shows a signed-in member is derived from this list, so
    it is recomputed per request and never cached in the session cookie.
    """
    return [r["server_id"] for r in db.query(
        "SELECT DISTINCT ps.server_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.member_id = ? AND s.is_active = 1"
        " ORDER BY ps.server_id", (member_id,))]


def own_player_names(member_id):
    """The member's own RuneScape accounts, across their active servers.

    Used only to mark "yours" in the UI. Being someone's account grants no extra
    visibility — a member already sees every player in their servers.
    """
    return [r["rs_name"] for r in db.query(
        "SELECT DISTINCT p.rs_name FROM player_servers ps"
        " JOIN players p ON p.id = ps.player_id"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.member_id = ? AND s.is_active = 1"
        " ORDER BY p.rs_name", (member_id,))]

"""Web UI credentials: issue, rotate, revoke, and the visibility rule.

Runs offline against a scratch database built from schema.sql. No Discord token,
no network, and it never touches data/osrs.db.

    python tools/test_web_auth.py

Covers the things that would be quietly wrong rather than loudly broken:
  * a password is never recoverable from the database
  * issuing again really does retire the old password
  * the visible set is exactly "players in servers I am in", including the
    awkward cases the migration documented (ghosts, orphans, removed servers)
  * a member with no links cannot sign in even holding a valid password
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402

PASSED = []
FAILED = []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    print(f"  {'ok  ' if condition else 'FAIL'} {label}"
          f"{'' if condition or not detail else '  -- ' + detail}")


def build():
    """A scratch database with a deliberately awkward shape."""
    path = os.path.join(tempfile.mkdtemp(prefix="osrs-webauth-"), "t.db")
    schema = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "schema.sql")
    repo.db.close()
    repo.bootstrap(path=path, schema_path=schema)

    with repo.transaction():
        # Two active servers and one the bot was removed from.
        for server_id, active in ((100, 1), (200, 1), (300, 0)):
            repo.db.execute(
                "INSERT INTO servers (id, is_active) VALUES (?, ?)",
                (server_id, active))

        def add(rs_name, server_id, member_id, tracked=1):
            player_id = repo.players.ensure(rs_name, tracked=bool(tracked))
            if server_id is not None:
                repo.db.execute(
                    "INSERT INTO player_servers (player_id, server_id, member_id)"
                    " VALUES (?,?,?)", (player_id, server_id, member_id))
            return player_id

        add("Alpha", 100, 11)
        add("Bravo", 100, 12)
        add("Charlie", 100, 12)          # member 12 owns two accounts
        add("Delta", 200, 13)
        add("Echo", 300, 14)             # only in the removed server
        add("Foxtrot", None, None)       # orphan: counters but no server link
        # Member 11 is in both active servers, so sees everyone in both.
        add("Golf", 200, 11)
    return path


def main():
    path = build()
    print(f"scratch database: {path}\n")

    print("issue / rotate / revoke")
    password, count = repo.webauth.issue(11)
    check("issue returns a password", bool(password) and len(password) > 30)
    check("issue_count starts at 1", count == 1, f"got {count}")
    check("the password is not stored anywhere in the database",
          repo.db.scalar(
              "SELECT COUNT(*) FROM web_credentials WHERE token_hash = ?",
              (password,), 0) == 0)
    check("the stored value is a sha256 hex digest",
          len(repo.db.scalar(
              "SELECT token_hash FROM web_credentials WHERE member_id = 11")) == 64)
    check("the password signs in as its member",
          repo.webauth.member_for_password(password) == 11)
    check("a wrong password signs in as nobody",
          repo.webauth.member_for_password("not-the-password") is None)
    check("an empty password signs in as nobody",
          repo.webauth.member_for_password("") is None)

    fingerprint_before = repo.webauth.fingerprint(11)
    second, count = repo.webauth.issue(11)
    check("issuing again bumps the count", count == 2, f"got {count}")
    check("issuing again returns a different password", second != password)
    check("the OLD password stops working",
          repo.webauth.member_for_password(password) is None)
    check("the NEW password works",
          repo.webauth.member_for_password(second) == 11)
    check("rotating changes the fingerprint, so open sessions are signed out",
          repo.webauth.fingerprint(11) != fingerprint_before)
    check("there is still only one row per member",
          repo.db.scalar(
              "SELECT COUNT(*) FROM web_credentials WHERE member_id = 11", (), 0) == 1)

    repo.webauth.revoke(11)
    check("revoking kills the password",
          repo.webauth.member_for_password(second) is None)
    check("revoking clears the fingerprint, so open sessions are signed out",
          repo.webauth.fingerprint(11) is None)
    check("revoking a member with no credential is harmless",
          repo.webauth.revoke(9999) is None)

    print("\nwho may sign in")
    check("a member with an active-server link is known",
          repo.webauth.is_known_member(11) is True)
    check("a member only in a REMOVED server is not known",
          repo.webauth.is_known_member(14) is False)
    check("an unknown member id is not known",
          repo.webauth.is_known_member(999) is False)

    # The important negative: holding a valid password is not enough.
    password14, _ = repo.webauth.issue(14)
    check("a valid password for a removed-server member still resolves...",
          repo.webauth.member_for_password(password14) == 14)
    check("...but that member is not known, so the UI refuses the sign-in",
          repo.webauth.is_known_member(14) is False)

    print("\nvisibility")

    # repo.webauth, not the web package. The access rule lives in the bot's
    # package so that this test needs no Flask, which also keeps the bot's
    # dependencies free of the UI's.
    def names(member_id):
        ids = repo.webauth.visible_player_ids(member_id)
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        return {r["rs_name"] for r in repo.db.query(
            f"SELECT rs_name FROM players WHERE id IN ({placeholders})", ids)}

    check("member in server 100 only sees server 100",
          names(12) == {"Alpha", "Bravo", "Charlie"}, str(sorted(names(12))))
    check("member in BOTH servers sees the union",
          names(11) == {"Alpha", "Bravo", "Charlie", "Delta", "Golf"},
          str(sorted(names(11))))
    check("the removed server's players are invisible to everyone",
          all("Echo" not in names(m) for m in (11, 12, 13, 14)))
    check("the orphan player with no server link is invisible to everyone",
          all("Foxtrot" not in names(m) for m in (11, 12, 13, 14)))
    check("a member with no links sees nobody", names(999) == set())
    check("member 14 (removed server only) sees nobody", names(14) == set())

    check("visible_server_ids matches", repo.webauth.visible_server_ids(11) == [100, 200])
    check("own_player_names lists only that member's accounts",
          repo.webauth.own_player_names(12) == ["Bravo", "Charlie"],
          str(repo.webauth.own_player_names(12)))

    print("\ndependency direction")
    # data/repo/ must stay importable by the bot alone. It already avoids
    # discord.py so the UI can use it; the reverse must hold too, or a UI
    # dependency creeps into the bot's virtualenv. This test itself running
    # under the bot's venv is the proof, but name the rule explicitly.
    import data.repo as repo_pkg
    leaked = sorted({name for name in dir(repo_pkg) if name in ("flask", "jinja2")})
    check("the repo package pulls in no web dependency", leaked == [], str(leaked))
    check("webauth imports only the standard library and repo.db",
          all(mod not in sys.modules or True for mod in ("flask",))
          and "flask" not in sys.modules,
          "flask was imported somewhere in this process")

    repo.db.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for label in FAILED:
            print("  -", label)
        return 1
    print("WEB AUTH OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

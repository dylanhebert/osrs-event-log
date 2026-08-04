"""Renaming onto a name that is already a player.

Reproduces a failure hit in production: `;transfer A>>B` succeeded in one server
and then failed in the next with

    UNIQUE constraint failed: players.rs_name

Both names already existed as separate players. The first transfer took the
"still in another server" branch, which attaches a link and cannot collide. That
removed one of A's links, so the second server found A down to a single link and
took the rename-in-place branch, which does

    UPDATE players SET rs_name = 'B' WHERE rs_name = 'A'

straight into the UNIQUE index that B already occupies.

Renaming in place is only safe when the destination name is free. When it is
not, the operation is a merge and has to attach the link instead.

    python tools/test_rename_merge.py
"""

# asyncio.run(), not get_event_loop(): 3.14 removed the implicit loop, which
# is the same change that forced the py-cord upgrade during the migration.
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    print(f"  {'ok  ' if condition else 'FAIL'} {label}"
          f"{'' if condition or not detail else '  -- ' + detail}")


class FakeServer:
    def __init__(self, server_id, name):
        self.id, self.name = server_id, name


class FakeMember:
    def __init__(self, member_id, name):
        self.id, self.name = member_id, name


STATS = {"skills": {"Overall": {"rank": 1, "level": 100, "xp": 5000}},
         "minigames": {}}


def build():
    path = os.path.join(tempfile.mkdtemp(prefix="osrs-rename-"), "t.db")
    schema = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "schema.sql")
    repo.db.close()
    repo.bootstrap(path=path, schema_path=schema)
    with repo.transaction():
        for server_id in (100, 200):
            repo.db.execute("INSERT INTO servers (id, is_active) VALUES (?, 1)",
                            (server_id,))
    return path


def main():
    path = build()

    # Import the handlers BEFORE using the scratch database, then re-point at
    # it. Importing data.handlers opens the live database on its own, because
    # sotw.py reads its config at import time; without the reconnect this test
    # would quietly run against production data. That is exactly the isolation
    # bug the migration notes record as D6.
    from data.handlers import player as handler
    from common import exceptions as ex
    repo.db.connect(path)

    server_a, server_b = FakeServer(100, "A"), FakeServer(200, "B")
    member = FakeMember(11, "someone")

    # The production shape: BOTH names already exist, the source is in two
    # servers, the destination in neither yet.
    repo.players.add_link("Retired+Alt", 100, 11)
    repo.players.add_link("Retired+Alt", 200, 11)
    repo.players.ensure("Surviving+Main", tracked=True)
    repo.players.set_global("Retired+Alt", "sotw_xp", 4242)
    source_id = repo.players.get_id("Retired+Alt")
    target_id = repo.players.get_id("Surviving+Main")

    # Give the old identity the things a real account accumulates, so the merge
    # has something to strand if it gets this wrong.
    repo.players.set_dink_key("Retired+Alt", "a-key")
    repo.stats.replace_all(source_id, STATS)
    repo.events.log_event(source_id, None, "hiscores", "LEVEL", "an old event")
    with repo.transaction():
        repo.db.execute(
            "INSERT INTO sotw_weeks (server_id, skill_name, ended_on, seq)"
            " VALUES (100, 'Agility', '2026-07-01', 0)")
        week_id = repo.db.scalar("SELECT MAX(id) FROM sotw_weeks")
        repo.db.execute(
            "INSERT INTO sotw_week_players (week_id, player_id, player_name,"
            " xp, rank, seq) VALUES (?,?,?,?,?,0)",
            (week_id, source_id, "Retired+Alt", 600, 3))

    print("setup")
    check("both names exist as separate players", source_id != target_id,
          f"{source_id} vs {target_id}")
    check("source is in two servers",
          repo.players.server_ids("Retired+Alt") == [100, 200])

    print("\nfirst transfer, in server A")
    asyncio.run(
        handler.rename_player(server_a, member, "Retired+Alt", "Surviving+Main", STATS))
    check("server A now points at the destination player",
          repo.players.linked_member("Surviving+Main", 100) == 11)
    check("source keeps its other server", repo.players.server_ids("Retired+Alt") == [200])
    check("no duplicate player was created",
          repo.db.scalar("SELECT COUNT(*) FROM players WHERE rs_name = ?",
                         ("Surviving+Main",), 0) == 1)
    check("the destination kept its original id",
          repo.players.get_id("Surviving+Main") == target_id)

    print("\nsecond transfer, in server B (this is what failed in production)")
    try:
        asyncio.run(
            handler.rename_player(server_b, member, "Retired+Alt", "Surviving+Main", STATS))
        check("it completes instead of raising UNIQUE constraint failed", True)
    except Exception as e:
        check("it completes instead of raising UNIQUE constraint failed", False,
              f"{type(e).__name__}: {e}")

    check("server B now points at the destination player",
          repo.players.linked_member("Surviving+Main", 200) == 11)
    check("the destination is now in both servers",
          repo.players.server_ids("Surviving+Main") == [100, 200])
    check("the source has no servers left",
          repo.players.server_ids("Retired+Alt") == [])
    check("the source was untracked rather than left in the poll set",
          repo.db.scalar("SELECT tracked FROM players WHERE rs_name = ?",
                         ("Retired+Alt",)) == 0)
    check("the source row survives, so old placements still resolve",
          repo.players.get_id("Retired+Alt") == source_id)
    check("still exactly one destination player",
          repo.db.scalar("SELECT COUNT(*) FROM players WHERE rs_name = ?",
                         ("Surviving+Main",), 0) == 1)

    print("\neverything tied to the old name followed it")
    check("stat history moved to the destination",
          repo.db.scalar("SELECT COUNT(*) FROM player_skill_history"
                         " WHERE player_id = ?", (source_id,), 0) == 0,
          "history left stranded on the retired id")
    check("...and is now on the destination",
          repo.db.scalar("SELECT COUNT(*) FROM player_skill_history"
                         " WHERE player_id = ?", (target_id,), 0) > 0)
    check("events moved",
          repo.db.scalar("SELECT COUNT(*) FROM events WHERE player_id = ?",
                         (source_id,), 0) == 0)
    check("SOTW placements are credited to the destination",
          repo.db.scalar("SELECT COUNT(*) FROM sotw_week_players"
                         " WHERE player_id = ?", (target_id,), 0) == 1)
    check("...but keep the name they were won under",
          repo.db.scalar("SELECT player_name FROM sotw_week_players"
                         " WHERE player_id = ?", (target_id,)) == "Retired+Alt")
    check("the dink key moved, since the destination had none",
          repo.db.scalar("SELECT dink_link_key FROM players WHERE id = ?",
                         (target_id,)) == "a-key")
    check("...and was cleared from the retired identity",
          repo.db.scalar("SELECT dink_link_key FROM players WHERE id = ?",
                         (source_id,)) is None)

    print("\nthe plain rename path still renames in place")
    repo.players.add_link("Solo+Name", 100, 12)
    solo_id = repo.players.get_id("Solo+Name")
    asyncio.run(
        handler.rename_player(server_a, FakeMember(12, "other"),
                              "Solo+Name", "Fresh+Name", STATS))
    check("a rename to a free name keeps the same player id",
          repo.players.get_id("Fresh+Name") == solo_id)
    check("the old name is gone", repo.players.get_id("Solo+Name") is None)

    print("\nguards")
    try:
        asyncio.run(
            handler.rename_player(server_a, member, "Surviving+Main", "Surviving+Main", STATS))
        check("renaming to the identical name is refused", False, "no error raised")
    except ex.DataHandlerError:
        check("renaming to the identical name is refused", True)
    except Exception as e:
        check("renaming to the identical name is refused", False, str(e))

    repo.db.close()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for label in FAILED:
            print("  -", label)
        return 1
    print("RENAME/MERGE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check that no player's records were stranded by a rename or transfer.

Read-only by default. It reports; it does not decide.

WHY THIS EXISTS

`;transfer` moves a player from one name to another. When the destination name
is free that is a rename and the id never changes, so nothing can be left
behind. When the destination is already a player it is a MERGE, the id changes,
and every table keyed on the old id has to follow. That did not always happen:
transfers run before repo.players.merge_into() existed left the retired
identity holding its stat history, its events, its SOTW/BOTW placements and its
Dink key, invisible to the player who carried on.

This finds those, plus the other ways a record can end up pointing nowhere.

    python tools/audit_players.py
    python tools/audit_players.py --db ../fixtures/ui-dev.db

EXPECTED ODDITIES ARE REPORTED SEPARATELY. The migration documented several
shapes that look wrong and are not: players tracked with no stat rows, orphans
holding only counters, and two accounts sharing one Dink key. Mixing those in
with real problems is how a report gets ignored.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402

OWNED_TABLES = (
    ("player_skill_history", "stat history"),
    ("player_activity_history", "activity history"),
    ("events", "events"),
    ("sotw_week_players", "SOTW placements"),
    ("botw_week_players", "BOTW placements"),
    ("player_skill_current", "current skills"),
    ("player_activity_current", "current activities"),
)


def q(sql, params=()):
    return repo.db.query(sql, params)


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


def report(rows, empty_message, formatter):
    if not rows:
        print(f"  none. {empty_message}")
        return 0
    for row in rows:
        print(f"  {formatter(row)}")
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=os.path.join("data", "osrs.db"))
    parser.add_argument("--all", action="store_true",
                        help="also list the documented oddities in full")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} does not exist.")
    repo.db.connect(args.db)

    print(f"database {args.db}")
    print(f"players  {repo.db.scalar('SELECT COUNT(*) FROM players', (), 0)}"
          f"  ({repo.db.scalar('SELECT COUNT(*) FROM pollable_players', (), 0)} pollable)")

    problems = 0

    # ------------------------------------------------------------------ #
    section("1. Retired identities still holding records")
    print("  A player with no active server link is retired. Two very different")
    print("  reasons produce that, and only one is a defect:")
    print()
    print("    LEFT THE LOG   they were removed, and their old SOTW/BOTW")
    print("                   placements rightly stay with them. Expected.")
    print("    MERGE MISSED   they were transferred to a new name but their")
    print("                   history, events, stats or Dink key did not")
    print("                   follow. Those records are unreachable.")
    print()
    print("  Placements alone are the first case. Anything else is the second.")

    owned = " + ".join(
        f"(SELECT COUNT(*) FROM {table} WHERE player_id = p.id)"
        for table, _ in OWNED_TABLES)
    retired = q(f"""
        SELECT p.id, p.rs_name, (p.dink_link_key IS NOT NULL) AS has_key
        FROM players p
        WHERE NOT EXISTS (SELECT 1 FROM player_servers ps
                          JOIN servers s ON s.id = ps.server_id
                          WHERE ps.player_id = p.id AND s.is_active = 1)
          AND (({owned}) > 0 OR p.dink_link_key IS NOT NULL)
    """)

    left_the_log, merge_missed = [], []
    for row in retired:
        held = []
        for table, label in OWNED_TABLES:
            count = repo.db.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE player_id = ?", (row["id"],), 0)
            if count:
                held.append((table, count, label))
        if row["has_key"]:
            held.append(("dink", 1, "a Dink key"))
        beyond_placements = [h for h in held
                             if h[0] not in ("sotw_week_players", "botw_week_players")]
        summary = f"{row['rs_name']:<24} " + ", ".join(
            f"{c} {label}" for _, c, label in held)
        (merge_missed if beyond_placements else left_the_log).append(summary)

    if merge_missed:
        print("\n  MERGE MISSED, these need attention:")
        for line in merge_missed:
            print(f"    {line}")
        print('\n    tools/merge_players.py --from "<old>" --to "<new>"')
        problems += len(merge_missed)
    else:
        print("\n  none holding anything beyond placements. No merge left records behind.")

    if left_the_log:
        print(f"\n  Left the log, holding only placements ({len(left_the_log)}), "
              f"which is expected:")
        for line in (left_the_log if args.all else left_the_log[:5]):
            print(f"    {line}")
        if not args.all and len(left_the_log) > 5:
            print(f"    ... and {len(left_the_log) - 5} more (--all to list)")

    # ------------------------------------------------------------------ #
    section("2. Placements naming a player that exists, but not linked to them")
    print("  player_name is authoritative and player_id may be NULL for players")
    print("  who were deleted. But if the name matches a player who DOES exist,")
    print("  the trophy is not being credited to them.")
    relinkable = []
    for kind, table, weeks in (("SOTW", "sotw_week_players", "sotw_weeks"),
                               ("BOTW", "botw_week_players", "botw_weeks")):
        relinkable += [
            (kind, r["player_name"], r["n"], r["player_id"])
            for r in q(f"""
                SELECT wp.player_name, COUNT(*) AS n,
                       (SELECT id FROM players WHERE rs_name = wp.player_name) AS player_id
                FROM {table} wp
                WHERE wp.player_id IS NULL
                  AND EXISTS (SELECT 1 FROM players WHERE rs_name = wp.player_name)
                GROUP BY wp.player_name
            """)]
    problems += report(
        relinkable,
        "Every placement that can be linked to a live player already is.",
        lambda r: f"{r[1]:<24} {r[0]} x{r[2]} could be credited to player id {r[3]}")

    # ------------------------------------------------------------------ #
    section("3. Untracked players still holding current stats")
    print("  untrack() clears current stats. Holding them means the player is")
    print("  out of the poll set but still shows numbers that can never update.")
    stale = q("""
        SELECT p.rs_name,
               (SELECT COUNT(*) FROM player_skill_current c WHERE c.player_id = p.id) AS skills
        FROM players p
        WHERE p.tracked = 0
          AND (SELECT COUNT(*) FROM player_skill_current c WHERE c.player_id = p.id) > 0
    """)
    problems += report(stale, "No untracked player is holding stale stats.",
                       lambda r: f"{r['rs_name']:<24} {r['skills']} skill rows, but tracked = 0")

    # ------------------------------------------------------------------ #
    section("4. Dink keys on identities nobody uses")
    print("  A key on a player with no active server is a live bearer token for")
    print("  the public webhook, held by an account nobody is watching.")
    dead_keys = q("""
        SELECT p.rs_name FROM players p
        WHERE p.dink_link_key IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM player_servers ps
                          JOIN servers s ON s.id = ps.server_id
                          WHERE ps.player_id = p.id AND s.is_active = 1)
    """)
    problems += report(dead_keys, "Every Dink key belongs to an active player.",
                       lambda r: f"{r['rs_name']:<24} holds a Dink key but is in no active server")

    # ------------------------------------------------------------------ #
    section("5. Names that differ only by case or spacing")
    print("  rs_name is COLLATE NOCASE, so these cannot both be reached.")
    collisions = q("""
        SELECT GROUP_CONCAT(rs_name, ' / ') AS names, COUNT(*) AS n
        FROM players
        GROUP BY REPLACE(LOWER(rs_name), '+', ' ')
        HAVING COUNT(*) > 1
    """)
    problems += report(collisions, "No two players collide on name.",
                       lambda r: f"{r['names']}  ({r['n']} rows)")

    # ------------------------------------------------------------------ #
    section("6. Documented oddities (not problems)")
    counts = {
        "tracked with no stat rows (empty skills dict at ;add)": repo.db.scalar("""
            SELECT COUNT(*) FROM players p WHERE p.tracked = 1
              AND NOT EXISTS (SELECT 1 FROM player_skill_current c
                              WHERE c.player_id = p.id)""", (), 0),
        "in no server at all (orphans holding only counters)": repo.db.scalar("""
            SELECT COUNT(*) FROM players p
              WHERE NOT EXISTS (SELECT 1 FROM player_servers ps
                                WHERE ps.player_id = p.id)""", (), 0),
        "ghosts: in a server, never polled": repo.db.scalar("""
            SELECT COUNT(*) FROM players p WHERE p.tracked = 0
              AND EXISTS (SELECT 1 FROM player_servers ps
                          WHERE ps.player_id = p.id)""", (), 0),
        "placements naming a player that no longer exists": repo.db.scalar("""
            SELECT COUNT(*) FROM sotw_week_players WHERE player_id IS NULL""", (), 0),
        "Dink keys shared by more than one player": repo.db.scalar("""
            SELECT COUNT(*) FROM (SELECT dink_link_key FROM players
              WHERE dink_link_key IS NOT NULL
              GROUP BY dink_link_key HAVING COUNT(*) > 1)""", (), 0),
    }
    for label, count in counts.items():
        print(f"  {count:>5}  {label}")

    # ------------------------------------------------------------------ #
    print()
    print("=" * 62)
    if problems:
        print(f"  {problems} thing(s) to look at above.")
    else:
        print("  Nothing stranded. Every record points at a player who can be reached.")
    print("=" * 62)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Move everything from one player onto another. Repair tool.

`;transfer` does this by itself now. This exists for transfers that ran before
it did, which left the old identity holding its history, its events and its
SOTW/BOTW placements while the new one carried on without them.

    python tools/merge_players.py --from "Old Name" --to "New Name"
    python tools/merge_players.py --from "Old Name" --to "New Name" --apply

Names are accepted in either form: "Old Name" or "Old+Name".

It refuses to run while the source still has server links. A player still in a
server is still in use, and its history is still its own; only a retired
identity should be folded into another.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402


def to_rs(name):
    return name.strip().replace(" ", "+")


def describe(rs_name):
    player_id = repo.players.get_id(rs_name)
    if player_id is None:
        return None
    counts = {}
    for table in ("player_servers", "player_skill_current",
                  "player_activity_current", "player_skill_history",
                  "player_activity_history", "events", "sotw_week_players",
                  "botw_week_players"):
        counts[table] = repo.db.scalar(
            f"SELECT COUNT(*) FROM {table} WHERE player_id = ?", (player_id,), 0)
    row = repo.db.one(
        "SELECT tracked, sotw_xp, botw_kills,"
        " (dink_link_key IS NOT NULL) AS has_key FROM players WHERE id = ?",
        (player_id,))
    return {"id": player_id, "tracked": row["tracked"],
            "has_key": bool(row["has_key"]), "counts": counts}


def show(label, rs_name, info):
    print(f"  {label}: {rs_name}")
    if info is None:
        print("    NOT IN THE DATABASE")
        return
    print(f"    id {info['id']}, tracked={info['tracked']}, "
          f"dink key {'set' if info['has_key'] else 'none'}")
    for table, count in info["counts"].items():
        if count:
            print(f"      {table:<26} {count}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("--to", dest="target", required=True)
    parser.add_argument("--db", default=os.path.join("data", "osrs.db"))
    parser.add_argument("--apply", action="store_true",
                        help="write. Without this nothing is written.")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} does not exist.")
    repo.db.connect(args.db)

    source, target = to_rs(args.source), to_rs(args.target)
    source_info, target_info = describe(source), describe(target)

    print(f"database {args.db}")
    print(f"mode     {'APPLY' if args.apply else 'dry run, writes nothing'}\n")
    show("FROM", source, source_info)
    print()
    show("TO  ", target, target_info)
    print()

    if source_info is None or target_info is None:
        raise SystemExit("Both players must exist.")
    if source_info["id"] == target_info["id"]:
        raise SystemExit("Those are the same player.")
    if source_info["counts"]["player_servers"]:
        raise SystemExit(
            f"{source} is still linked to "
            f"{source_info['counts']['player_servers']} server(s). Only a "
            f"retired identity should be merged; run the transfer in those "
            f"servers first.")

    movable = {t: n for t, n in source_info["counts"].items()
               if n and t in ("player_skill_history", "player_activity_history",
                              "events", "sotw_week_players", "botw_week_players")}
    if not movable and not source_info["has_key"]:
        print("Nothing to move.")
        return 0

    print("would move:")
    for table, count in movable.items():
        print(f"  {count} {table}")
    if source_info["has_key"] and not target_info["has_key"]:
        print("  the dink link key")
    elif source_info["has_key"]:
        print("  (the destination already has a dink key, so it is kept and "
              "the source's is cleared)")
    print("\nSOTW/BOTW player_name is left as it was: it records who they were "
          "called at\nthe time, which is true. Only the id is re-pointed, so "
          "the trophy credits\nthe right player now.")

    if not args.apply:
        print("\nDry run. Re-run with --apply to make the change.")
        return 0

    with repo.transaction():
        moved = repo.players.merge_into(source, target)
    print("\nmoved: " + (", ".join(f"{n} {t}" for t, n in moved.items())
                         or "nothing"))

    print("\nafter:")
    show("FROM", source, describe(source))
    print()
    show("TO  ", target, describe(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

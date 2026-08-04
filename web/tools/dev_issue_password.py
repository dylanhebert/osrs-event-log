"""DEV ONLY. Issue a web password against a LOCAL snapshot.

In production the bot does this, from ;webpassword. There is no bot running
locally, so this stands in for it: same repo function, same rotation, same
hash-only storage.

It WRITES, which the web UI never does. That is the point of it being a separate
script rather than anything the app can reach, and it is why it refuses to touch
a database whose path looks like production.

    web/.venv/Scripts/python -m web.tools.dev_issue_password           # busiest member
    web/.venv/Scripts/python -m web.tools.dev_issue_password --list
    web/.venv/Scripts/python -m web.tools.dev_issue_password --member 123
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "osrs-event-log"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "web" / ".env")

from data import repo  # noqa: E402


def guard(db_path):
    """Refuse anything that is not obviously a local throwaway.

    The bot's own working database lives at osrs-event-log/data/osrs.db and the
    droplet's is the only copy of live state. Writing a credential into either
    by accident would be recoverable but stupid, so make it impossible to do
    without renaming the file.
    """
    resolved = Path(db_path).resolve()
    if resolved.parent.name != "fixtures":
        raise SystemExit(
            f"refusing to write to {resolved}\n"
            f"This script only writes to a snapshot under fixtures/. Pull one "
            f"with the .backup command in docs/web-ui.md.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--member", type=int, default=None)
    parser.add_argument("--list", action="store_true",
                        help="show members and how many players each would see")
    args = parser.parse_args()

    db_path = os.environ.get("OSRS_DB_PATH")
    if not db_path:
        raise SystemExit("OSRS_DB_PATH is not set; see web/.env.example")
    guard(db_path)

    repo.db.connect(db_path)

    rows = repo.db.query("""
        SELECT ps.member_id,
               (SELECT COUNT(DISTINCT ps2.player_id) FROM player_servers ps2
                 WHERE ps2.server_id IN (
                    SELECT ps3.server_id FROM player_servers ps3
                    JOIN servers s3 ON s3.id = ps3.server_id
                    WHERE s3.is_active = 1 AND ps3.member_id = ps.member_id)) AS visible,
               COUNT(DISTINCT ps.server_id) AS servers,
               COUNT(DISTINCT ps.player_id) AS own
        FROM player_servers ps
        JOIN servers s ON s.id = ps.server_id
        WHERE s.is_active = 1 AND ps.member_id IS NOT NULL
        GROUP BY ps.member_id
        ORDER BY visible DESC, servers DESC
    """)

    if args.list:
        # Member ids are real Discord user ids, so they are printed as an index
        # rather than in full. --member still takes the real id if you know it.
        print(f"{'#':>3}  {'visible':>7}  {'servers':>7}  {'own':>4}")
        for i, row in enumerate(rows, 1):
            print(f"{i:>3}  {row['visible']:>7}  {row['servers']:>7}  {row['own']:>4}")
        print("\nRun without --list to issue a password for the busiest member.")
        return 0

    if not rows:
        raise SystemExit("no members with an active-server link in this snapshot")

    member_id = args.member if args.member is not None else rows[0]["member_id"]
    match = next((r for r in rows if r["member_id"] == member_id), None)
    if match is None:
        raise SystemExit(f"member {member_id} has no active-server link here")

    password, count = repo.webauth.issue(member_id)
    repo.db.close()

    print(f"\nsnapshot   {db_path}")
    print(f"member     <redacted discord id>")
    print(f"sees       {match['visible']} players across {match['servers']} "
          f"server(s), owns {match['own']}")
    print(f"issue #    {count}")
    print(f"\npassword:  {password}\n")
    print("Paste that into the sign-in box. Running this again replaces it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

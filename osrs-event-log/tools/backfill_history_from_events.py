"""Rebuild stat history from the text of old Discord posts.

    python tools/backfill_history_from_events.py            # dry run
    python tools/backfill_history_from_events.py --apply

`player_skill_history` only starts at the SQLite migration, because before that
nothing recorded a player's numbers anywhere: the looper compared them, posted
a message and threw them away. So the player charts have one day of data and
draw nothing for almost everybody.

The numbers are not gone, though. They were printed into the messages, and
tools/backfill_events_from_discord.py has since pulled six years of those back
into `events`. This reads the totals out of that text.

WHAT COUNTS AS A LIFETIME TOTAL
-------------------------------
Only two shapes, both written by activity/PlayerUpdate.py from the hiscores
payload itself, so both are exact:

    Total <Skill> XP: 217,223                       -> that skill
    Total level: 977 | Total Overall XP: 3,358,189  -> Overall, with its level

`Skill of the Week - Current <Skill> XP: N` LOOKS like the first and is not.
PlayerUpdate builds it from `new_sotw_xp`, which `add_to_player_entry_global`
accumulates over the week and resets when the week rolls over. Reading it as a
lifetime total would draw a sawtooth of weekly gains under the real curve. Read
the code before adding a third pattern here.

WHY IT FILTERS AS WELL AS PARSES
--------------------------------
Two things upstream put the occasional point in the wrong place:

  * The bot sometimes posted several players' updates in one message, and the
    Discord backfill attributed every unit in a message to the first player it
    recognised. Measured at 28 rows in 46,027, but a single wrong point is very
    visible on a chart: it rescales the whole y axis.
  * `Total level: ... | Total Overall XP: ...` is a footer with no name in it,
    so it inherits whichever player the rest of the message named. In a batched
    message that inheritance can be wrong.

So a point is dropped when:

  1. the message carries a bold title naming a DIFFERENT known player
  2. it would make the series go backwards -- XP never decreases, so a value
     below the running maximum is proof the point does not belong here
  3. it exceeds what the player has now, which is the same argument from the
     other end

Everything dropped is counted and sampled in the report rather than discarded
quietly.

SAFETY
------
Nothing in the bot's change-detection path reads these tables. `repo.stats`
only ever inserts into them; the looper compares against
`player_skill_current`. Writing here cannot cause a poll to see a change, so it
cannot cause a Discord post.

Idempotent: a row is skipped when one already exists for the same player,
skill and timestamp. Recovered rows carry `recovered = 1`, so they are
distinguishable from polled ones, the chart can join them differently, and the
whole import can be undone with

    DELETE FROM player_skill_history WHERE recovered = 1;
"""

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402

# Absolute lifetime totals only. See the docstring on why the Skill of the Week
# line is not here.
TOTAL_XP = re.compile(r"Total ([A-Za-z ]+?) XP: ([\d,]+)")
OVERALL = re.compile(r"Total level: ([\d,]+)\s*\|\s*Total Overall XP: ([\d,]+)")
LEVELLED = re.compile(r"levelled up ([A-Za-z ]+?) to (\d+)", re.IGNORECASE)
BOLD_TITLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
WEEKLY = re.compile(r"(?:Skill|Boss) of the Week - ")


def as_int(text):
    return int(text.replace(",", ""))


def read_totals(message):
    """[(skill, level or None, xp)] of lifetime totals stated in one message."""
    found = []
    if not message:
        return found

    overall = OVERALL.search(message)
    if overall:
        found.append(("Overall", as_int(overall.group(1)),
                      as_int(overall.group(2))))

    # "levelled up Fishing to 72" in the same unit gives the level to go with
    # the XP. Absent for a threshold milestone, where the level did not change.
    levels = {m.group(1).strip(): int(m.group(2))
              for m in LEVELLED.finditer(message)}

    for match in TOTAL_XP.finditer(message):
        line_start = message.rfind("\n", 0, match.start()) + 1
        if WEEKLY.search(message[line_start:match.start()]):
            continue
        skill = match.group(1).strip()
        if skill == "Overall":
            continue        # already taken above, and with its total level
        found.append((skill, levels.get(skill), as_int(match.group(2))))
    return found


def title_owner(message, name_index):
    """The player a message's bold title names, or None if it names nobody.

    Longest first, because RuneScape names contain spaces and one can be a
    prefix of another.
    """
    match = BOLD_TITLE.search(message or "")
    if not match:
        return None
    head = match.group(1).strip().lower()
    for name in name_index["ordered"]:
        if head.startswith(name):
            return name_index["by_name"][name]
    return None


def build_name_index():
    by_name = {}
    for row in repo.db.query("SELECT id, rs_name, display_name FROM players"):
        for name in {row["display_name"], (row["rs_name"] or "").replace("+", " ")}:
            if name:
                by_name[name.lower()] = row["id"]
    return {"by_name": by_name,
            "ordered": sorted(by_name, key=len, reverse=True)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=os.path.join("data", "osrs.db"))
    parser.add_argument("--apply", action="store_true",
                        help="write. Without this nothing is written.")
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} does not exist.")
    repo.db.connect(args.db)

    columns = [r[1] for r in repo.db.query("PRAGMA table_info(player_skill_history)")]
    if "recovered" not in columns:
        raise SystemExit(
            "player_skill_history.recovered is missing. Run\n"
            "  python tools/migrate_add_web_auth.py --db " + args.db)

    skill_ids = {r["name"]: r["id"] for r in repo.db.query("SELECT id, name FROM skills")}
    name_index = build_name_index()
    # updated_at as well as xp, because the ceiling only applies to a point
    # older than the snapshot it is being compared with. An event newer than
    # the last poll of that skill is legitimately higher, and that is not a
    # corner case: it is every event since the most recent poll.
    current_xp = {
        (r["player_id"], r["skill_id"]): (r["xp"], r["updated_at"])
        for r in repo.db.query(
            "SELECT player_id, skill_id, xp, updated_at FROM player_skill_current")}

    rows = repo.db.query(
        "SELECT player_id, message, occurred_at FROM events"
        " WHERE source = 'hiscores' ORDER BY occurred_at, id")
    print(f"reading {len(rows):,} hiscores events")

    dropped = collections.Counter()
    samples = collections.defaultdict(list)
    unknown_skills = collections.Counter()
    series = collections.defaultdict(list)     # (player, skill_id) -> [(ts, lvl, xp)]

    for row in rows:
        message = row["message"]
        owner = title_owner(message, name_index)
        if owner is not None and owner != row["player_id"]:
            # A titled unit stored against somebody else: the message batched
            # several players and attribution went to the first of them.
            dropped["title names another player"] += 1
            if len(samples["title"]) < args.samples:
                samples["title"].append((row["player_id"], owner, (message or "")[:70]))
            continue
        for skill, level, xp in read_totals(message):
            skill_id = skill_ids.get(skill)
            if skill_id is None:
                unknown_skills[skill] += 1
                dropped["skill not in the database"] += 1
                continue
            series[(row["player_id"], skill_id)].append(
                (row["occurred_at"], level, xp))

    extracted = sum(len(v) for v in series.values())
    print(f"extracted {extracted:,} candidate points "
          f"across {len(series):,} player/skill series")

    # --- filter: a series can only ever go up -------------------------------
    kept = []
    for (player_id, skill_id), values in series.items():
        values.sort(key=lambda v: v[0])
        ceiling, as_of = current_xp.get((player_id, skill_id), (None, None))
        peak = -1
        for occurred_at, level, xp in values:
            if xp < peak:
                dropped["would make the series go backwards"] += 1
                if len(samples["back"]) < args.samples:
                    samples["back"].append((player_id, skill_id, peak, xp, occurred_at))
                continue
            # A player who has fallen off the hiscores keeps a current row of
            # 0, or none at all, and there is no ceiling to check against; that
            # is D1, not a bad point. Nor does the ceiling apply to a point
            # recorded after the snapshot it would be compared with.
            if (ceiling is not None and ceiling > 0 and xp > ceiling
                    and as_of and occurred_at <= as_of):
                dropped["higher than the player's xp at that time"] += 1
                if len(samples["ceiling"]) < args.samples:
                    samples["ceiling"].append((player_id, skill_id, xp, ceiling))
                continue
            peak = xp
            kept.append((player_id, skill_id, level, xp, occurred_at))

    print(f"{len(kept):,} points survive the sanity filters")
    if dropped:
        print("\ndropped:")
        for reason, count in dropped.most_common():
            print(f"  {count:6,}  {reason}")
    if unknown_skills:
        print(f"  skills not in the database: {dict(unknown_skills)}")
    for label, rows_ in samples.items():
        for s in rows_[:args.samples]:
            print(f"    [{label}] {s}")

    # --- what already exists, so a re-run adds nothing ----------------------
    existing = {
        (r["player_id"], r["skill_id"], r["recorded_at"])
        for r in repo.db.query(
            "SELECT player_id, skill_id, recorded_at FROM player_skill_history")}
    fresh = [k for k in kept if (k[0], k[1], k[4]) not in existing]
    print(f"\n{len(fresh):,} new, {len(kept) - len(fresh):,} already present")

    if fresh:
        years = collections.Counter(k[4][:4] for k in fresh)
        print("\nby year:")
        for year in sorted(years):
            print(f"  {year}  {years[year]:6,}")
        players = len({k[0] for k in fresh})
        print(f"\ncovering {players} players")

    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply to insert.")
        return 0

    print(f"\nInserting {len(fresh):,} rows...")
    with repo.transaction():
        for player_id, skill_id, level, xp, occurred_at in fresh:
            repo.db.execute(
                "INSERT INTO player_skill_history"
                " (player_id, skill_id, level, xp, rank, recorded_at, recovered)"
                " VALUES (?,?,?,?,NULL,?,1)",
                # Level is not in every message; the hiscores level for that XP
                # is not derivable here without a table, so 0 stands for "not
                # stated" and the chart plots XP anyway.
                (player_id, skill_id, level or 0, xp, occurred_at))
    total = repo.db.scalar("SELECT COUNT(*) FROM player_skill_history", (), 0)
    drawable = repo.db.scalar(
        "SELECT COUNT(*) FROM (SELECT player_id FROM player_skill_history"
        " GROUP BY player_id HAVING COUNT(DISTINCT recorded_at) >= 2)", (), 0)
    print(f"Done. player_skill_history now holds {total:,} rows.")
    print(f"{drawable} players now have enough history to draw a chart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

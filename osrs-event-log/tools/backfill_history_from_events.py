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

WHAT COUNTS AS A RUNNING TOTAL
------------------------------
Skills state theirs in the code block, and both shapes are written by
activity/PlayerUpdate.py straight from the hiscores payload, so both are exact:

    Total <Skill> XP: 217,223                       -> that skill
    Total level: 977 | Total Overall XP: 3,358,189  -> Overall, with its level

BOSSES AND MINIGAMES PUT IT IN THE TITLE INSTEAD, and the block holds a delta:

    **X has killed Vardorvis 84 times**```c
    New kills logged: 6 | Current rank: 147,117```
             ^ the total                ^ NOT the total

Reading the block the way the skill parser does would plot session sizes rather
than a career. `New kills logged` and `New collections logged` are never read.

TWO PATTERNS ARE TRAPS, BOTH THE SAME TRAP
------------------------------------------
    Skill of the Week - Current Fishing XP: 141,652
    Boss of the Week - Current Zulrah kills: 1

They have the shape of a total and are weekly accumulators. PlayerUpdate builds
them from `new_sotw_xp` / `new_botw_kills`, which `add_to_player_entry_global`
adds to across the week and resets when the week rolls over. Read as totals
they would draw a sawtooth of weekly gains under every real curve, and nothing
about the output would look wrong. Read the code before adding a pattern here.

WHY IT FILTERS AS WELL AS PARSES
--------------------------------
Two things upstream put the occasional point in the wrong place:

  * The bot sometimes posted several players' updates in one message, and the
    Discord backfill attributed every unit in a message to the first player it
    recognised. Measured at 28 rows in 46,027, but a single wrong point is very
    visible on a chart: it rescales the whole y axis.
  * `Total level: ... | Total Overall XP: ...` and `Total kill count: ...` carry
    no name, so they inherit whichever player the rest of the message named. In
    a batched message that inheritance can be wrong.

So a point is dropped when:

  1. the message carries a bold title naming a DIFFERENT known player
  2. it would make the series go backwards -- XP and kill counts never
     decrease, so a value below the running maximum cannot belong here. A few
     activities are ratings rather than counts and really do fall; CAN_DECREASE
     lists them and they skip this check.
  3. it exceeds what the player held at that time, which is the same argument
     from the other end

Everything dropped is counted in the report, and the third reason names the
accounts it happened to: a run of them means one account's current figures
disagree with its own posted history, which is worth seeing rather than
silently truncating that player's chart.

SAFETY
------
Nothing in the bot's change-detection path reads these tables. `repo.stats`
only ever inserts into them; the looper compares against
`player_skill_current`. Writing here cannot cause a poll to see a change, so it
cannot cause a Discord post.

Idempotent: a row is skipped when one already exists for the same player,
skill or activity, and timestamp. Recovered rows carry `recovered = 1`, so they
are distinguishable from polled ones, the chart can join them differently, and
the whole import can be undone with

    DELETE FROM player_skill_history    WHERE recovered = 1;
    DELETE FROM player_activity_history WHERE recovered = 1;
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

# --------------------------------------------------------------------------- #
# Activities
# --------------------------------------------------------------------------- #
# Bosses and minigames state their running total differently from skills: the
# absolute is usually in the TITLE and the code block holds the delta.
#
#   **X has killed Vardorvis 84 times**```c
#   New kills logged: 6 | Current rank: 147,117```
#            ^ absolute                ^ delta
#
# So reading only the code block, which is what works for skills, gets the
# wrong number. `New kills logged` and `New collections logged` are deltas and
# are never read.
#
# `Boss of the Week - Current <Boss> kills: N` is the same trap as its skill
# counterpart: new_botw_kills is accumulated across the week and reset. WEEKLY
# above excludes both.
KILLED_N_TIMES = re.compile(
    r"has (?:killed|completed) (.+?) (?:at least )?([\d,]+) times", re.IGNORECASE)
PROGRESSED_N = re.compile(
    r"has progressed (.+?) (?:at least )?([\d,]+) times", re.IGNORECASE)
CLUES_N = re.compile(
    r"has completed (?:at least )?([\d,]+) ([A-Za-z]+) Clue Scrolls", re.IGNORECASE)
CLUES_BLOCK = re.compile(r"([A-Za-z]+) clues completed: ([\d,]+)", re.IGNORECASE)
TOTAL_KILL_COUNT = re.compile(r"Total kill count: ([\d,]+)")
TOTAL_NAMED_COUNT = re.compile(r"Total ([A-Za-z' ]+?) count: ([\d,]+)")
ON_HISCORES = re.compile(
    r"(?:killed|completed) (.+?) enough times to be on the hiscores",
    re.IGNORECASE)

# Activities whose number is a RATING or a best score rather than a running
# count, so it can legitimately go down. The "must not decrease" filter is
# skipped for these; a Bounty Hunter score really does fall.
CAN_DECREASE = {
    "Bounty Hunter - Hunter", "Bounty Hunter - Rogue",
    "Bounty Hunter (Legacy) - Hunter", "Bounty Hunter (Legacy) - Rogue",
    "Colosseum Glory", "LMS - Rank", "PvP Arena - Rank", "Soul Wars Zeal",
}


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


def resolve_activity(text, activity_index):
    """The activity an extracted phrase names, or None.

    Longest first: "Chambers of Xeric: Challenge Mode" must not lose to
    "Chambers of Xeric", and "Clue Scrolls (all)" is a real name too.
    """
    if not text:
        return None
    cleaned = text.strip().strip(".!").lower()
    exact = activity_index["by_name"].get(cleaned)
    if exact:
        return exact
    for name in activity_index["ordered"]:
        if cleaned.endswith(name) or cleaned.startswith(name):
            return activity_index["by_name"][name]
    return None


def read_activity_totals(message, activity_index):
    """[(activity name, score)] of running totals stated in one message.

    Deltas are never read. `New kills logged: 6` is how many since last time,
    and treating it as a total would draw a chart of session sizes.
    """
    found = []
    if not message:
        return found

    title_match = BOLD_TITLE.search(message)
    title = title_match.group(1) if title_match else ""

    # "...has killed Vardorvis 84 times" / "...has completed X 12 times"
    for pattern in (KILLED_N_TIMES, PROGRESSED_N):
        for match in pattern.finditer(title):
            name = resolve_activity(match.group(1), activity_index)
            if name:
                found.append((name, as_int(match.group(2))))

    # "...has completed at least 100 Hard Clue Scrolls"
    for match in CLUES_N.finditer(title):
        name = resolve_activity(
            f"clue scrolls ({match.group(2).lower()})", activity_index)
        if name:
            found.append((name, as_int(match.group(1))))

    for match in CLUES_BLOCK.finditer(message):
        tier = match.group(1).lower()
        # "Total clues completed: 254" is the all-tiers figure.
        name = resolve_activity(
            "clue scrolls (all)" if tier == "total" else f"clue scrolls ({tier})",
            activity_index)
        if name:
            found.append((name, as_int(match.group(2))))

    # "Total kill count: 31,762" names no activity, so it takes the title's.
    # Skipped when the title named none, rather than guessed at.
    for match in TOTAL_KILL_COUNT.finditer(message):
        line_start = message.rfind("\n", 0, match.start()) + 1
        if WEEKLY.search(message[line_start:match.start()]):
            continue
        subject = None
        for pattern in (KILLED_N_TIMES, PROGRESSED_N, ON_HISCORES):
            hit = pattern.search(title)
            if hit:
                subject = resolve_activity(hit.group(1), activity_index)
                break
        if subject:
            found.append((subject, as_int(match.group(1))))

    # "Total Barrows Chests count: 512" describes itself.
    for match in TOTAL_NAMED_COUNT.finditer(message):
        if match.group(1).strip().lower() == "kill":
            continue                      # handled above, needs the title
        line_start = message.rfind("\n", 0, match.start()) + 1
        if WEEKLY.search(message[line_start:match.start()]):
            continue
        name = resolve_activity(match.group(1), activity_index)
        if name:
            found.append((name, as_int(match.group(2))))

    # Deduplicate: a message can state the same figure twice, once in the
    # title and once in the block.
    seen, unique = set(), []
    for name, score in found:
        if (name, score) not in seen:
            seen.add((name, score))
            unique.append((name, score))
    return unique


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
    activity_rows = repo.db.query("SELECT id, name FROM activities")
    activity_ids = {r["name"]: r["id"] for r in activity_rows}
    activity_index = {
        "by_name": {r["name"].lower(): r["name"] for r in activity_rows},
        "ordered": sorted((r["name"].lower() for r in activity_rows),
                          key=len, reverse=True),
    }
    name_index = build_name_index()

    # updated_at as well as the value, because the ceiling only applies to a
    # point older than the snapshot it is being compared with. An event newer
    # than the last poll is legitimately higher, and that is not a corner case:
    # it is every event since the most recent poll.
    current = {
        ("skill", r["player_id"], r["skill_id"]): (r["xp"], r["updated_at"])
        for r in repo.db.query(
            "SELECT player_id, skill_id, xp, updated_at FROM player_skill_current")}
    current.update({
        ("activity", r["player_id"], r["activity_id"]): (r["score"], r["updated_at"])
        for r in repo.db.query(
            "SELECT player_id, activity_id, score, updated_at"
            " FROM player_activity_current")})

    rows = repo.db.query(
        "SELECT player_id, message, occurred_at FROM events"
        " WHERE source = 'hiscores' ORDER BY occurred_at, id")
    print(f"reading {len(rows):,} hiscores events")

    dropped = collections.Counter()
    samples = collections.defaultdict(list)
    unknown = collections.Counter()
    # (kind, player, id) -> [(ts, level or None, value)]
    series = collections.defaultdict(list)

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
                unknown[f"skill {skill}"] += 1
                dropped["name not in the database"] += 1
                continue
            series[("skill", row["player_id"], skill_id)].append(
                (row["occurred_at"], level, xp))

        for activity, score in read_activity_totals(message, activity_index):
            activity_id = activity_ids.get(activity)
            if activity_id is None:
                unknown[f"activity {activity}"] += 1
                dropped["name not in the database"] += 1
                continue
            series[("activity", row["player_id"], activity_id)].append(
                (row["occurred_at"], None, score))

    extracted = sum(len(v) for v in series.values())
    skill_series = sum(1 for k in series if k[0] == "skill")
    print(f"extracted {extracted:,} candidate points across {len(series):,} series"
          f"  ({skill_series:,} skill, {len(series) - skill_series:,} activity)")

    activity_names = {v: k for k, v in activity_ids.items()}
    ceiling_players = collections.Counter()
    kept = []
    for (kind, owner_id, thing_id), values in series.items():
        values.sort(key=lambda v: v[0])
        ceiling, as_of = current.get((kind, owner_id, thing_id), (None, None))
        # A kill count or an XP total only ever rises, so a value below the
        # running maximum cannot belong to this series. A few activities are
        # ratings rather than counts and really do fall; those skip the check.
        rising = not (kind == "activity"
                      and activity_names.get(thing_id) in CAN_DECREASE)
        peak = -1
        for occurred_at, level, value in values:
            if rising and value < peak:
                dropped["would make the series go backwards"] += 1
                if len(samples["back"]) < args.samples:
                    samples["back"].append((kind, owner_id, thing_id, peak, value))
                continue
            # A player who has fallen off the hiscores keeps a current row of
            # 0, or none at all, and there is no ceiling to check against; that
            # is D1, not a bad point.
            if (ceiling is not None and ceiling > 0 and value > ceiling
                    and as_of and occurred_at <= as_of):
                dropped["higher than the player had at that time"] += 1
                # Named, not just counted. A run of these means one account's
                # current figures disagree with its own posted history, which
                # is worth knowing about rather than silently truncating that
                # player's chart.
                ceiling_players[owner_id] += 1
                if len(samples["ceiling"]) < args.samples:
                    samples["ceiling"].append((kind, owner_id, thing_id, value, ceiling))
                continue
            if rising:
                peak = value
            kept.append((kind, owner_id, thing_id, level, value, occurred_at))

    print(f"{len(kept):,} points survive the sanity filters")
    if dropped:
        print("\ndropped:")
        for reason, count in dropped.most_common():
            print(f"  {count:6,}  {reason}")
    if unknown:
        print(f"  names not in the database: {dict(unknown.most_common(6))}")
    if ceiling_players:
        player_names = {r["id"]: r["rs_name"]
                        for r in repo.db.query("SELECT id, rs_name FROM players")}
        print(f"\n  {len(ceiling_players)} account(s) posted figures above what"
              f" they hold now, so those points were left out:")
        for owner_id, count in ceiling_players.most_common(5):
            print(f"    {count:6,}  {player_names.get(owner_id, owner_id)}")
    for label, rows_ in samples.items():
        for s in rows_[:args.samples]:
            print(f"    [{label}] {s}")

    # --- what already exists, so a re-run adds nothing ----------------------
    existing = {
        ("skill", r["player_id"], r["skill_id"], r["recorded_at"])
        for r in repo.db.query(
            "SELECT player_id, skill_id, recorded_at FROM player_skill_history")}
    existing |= {
        ("activity", r["player_id"], r["activity_id"], r["recorded_at"])
        for r in repo.db.query(
            "SELECT player_id, activity_id, recorded_at FROM player_activity_history")}
    fresh = [k for k in kept if (k[0], k[1], k[2], k[5]) not in existing]
    print(f"\n{len(fresh):,} new, {len(kept) - len(fresh):,} already present")

    if fresh:
        years = collections.Counter(k[5][:4] for k in fresh)
        print("\nby year:")
        for year in sorted(years):
            print(f"  {year}  {years[year]:6,}")
        kinds = collections.Counter(k[0] for k in fresh)
        print(f"\nskill points {kinds['skill']:,} · "
              f"activity points {kinds['activity']:,} · "
              f"{len({k[1] for k in fresh})} players")

    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply to insert.")
        return 0

    print(f"\nInserting {len(fresh):,} rows...")
    with repo.transaction():
        for kind, owner_id, thing_id, level, value, occurred_at in fresh:
            if kind == "skill":
                repo.db.execute(
                    "INSERT INTO player_skill_history"
                    " (player_id, skill_id, level, xp, rank, recorded_at, recovered)"
                    " VALUES (?,?,?,?,NULL,?,1)",
                    # Level is not in every message and the hiscores level for
                    # a given XP is not derivable here without a table, so 0
                    # stands for "not stated". The chart plots XP regardless.
                    (owner_id, thing_id, level or 0, value, occurred_at))
            else:
                repo.db.execute(
                    "INSERT INTO player_activity_history"
                    " (player_id, activity_id, score, rank, recorded_at, recovered)"
                    " VALUES (?,?,?,NULL,?,1)",
                    (owner_id, thing_id, value, occurred_at))

    for table, label in (("player_skill_history", "skill"),
                         ("player_activity_history", "activity")):
        total = repo.db.scalar(f"SELECT COUNT(*) FROM {table}", (), 0)
        drawable = repo.db.scalar(
            f"SELECT COUNT(*) FROM (SELECT player_id FROM {table}"
            " GROUP BY player_id HAVING COUNT(DISTINCT recorded_at) >= 2)", (), 0)
        print(f"{table} now holds {total:,} rows; "
              f"{drawable} players have drawable {label} history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

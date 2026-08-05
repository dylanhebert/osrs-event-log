"""What the history recovery reads out of a message, and what it refuses to.

    python tools/test_history_backfill.py

The case that matters most is the Skill of the Week line. It has the same shape
as a lifetime total and is a weekly accumulator, so reading it would draw a
sawtooth of weekly gains underneath the real curve, on every chart, with
nothing to suggest anything was wrong. Everything else here is ordinary parsing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.backfill_history_from_events import (  # noqa: E402
    read_activity_totals, read_totals, title_owner)

# A handful of real activity names, including the shapes that make matching
# awkward: one name that is a prefix of another, and the parenthesised clues.
ACTIVITIES = [
    "Vardorvis", "Zulrah", "Barrows Chests", "Collections Logged",
    "Chambers of Xeric", "Chambers of Xeric: Challenge Mode",
    "Theatre of Blood", "Clue Scrolls (all)", "Clue Scrolls (hard)",
    "Clue Scrolls (beginner)",
]
ACTIVITY_INDEX = {
    "by_name": {name.lower(): name for name in ACTIVITIES},
    "ordered": sorted((name.lower() for name in ACTIVITIES), key=len, reverse=True),
}


def activities(message):
    return read_activity_totals(message, ACTIVITY_INDEX)

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"       got  {got}")
        print(f"       want {want}")
        failures.append(label)


def main():
    print("\nlifetime totals are read")
    check(
        "a levelling message gives skill, level and xp",
        read_totals("**Someone levelled up Hitpoints to 57**```c\n"
                    "18,955 XP gained | Total Hitpoints XP: 217,223```"),
        [("Hitpoints", 57, 217223)])
    check(
        "the Overall footer gives total level and overall xp",
        read_totals("```c\nTotal level: 977 | Total Overall XP: 3,358,189```"),
        [("Overall", 977, 3358189)])
    check(
        "a threshold milestone has xp but states no level",
        read_totals("**Someone has achieved 40,000,000 Ranged XP**```c\n"
                    "41,938 XP gained | Total Ranged XP: 40,001,204```"),
        [("Ranged", None, 40001204)])
    check(
        "one message can carry a skill and the Overall footer",
        read_totals("**Someone levelled up Mining to 70**```c\n"
                    "Total Mining XP: 737,627``````c\n"
                    "Total level: 1,204 | Total Overall XP: 9,900,001```"),
        [("Overall", 1204, 9900001), ("Mining", 70, 737627)])

    print("\nTHE WEEKLY ACCUMULATOR IS NOT A LIFETIME TOTAL")
    # PlayerUpdate builds this from new_sotw_xp, which
    # add_to_player_entry_global accumulates across the week and resets. Read
    # as lifetime XP it would put a sawtooth under every chart.
    check(
        "Skill of the Week is ignored entirely",
        read_totals("```c\nSkill of the Week - Current Fishing XP: 141,652```"),
        [])
    check(
        "Boss of the Week is ignored entirely",
        read_totals("```c\nBoss of the Week - Current Scurrius kills: 42```"),
        [])
    check(
        "a real total in the same message still survives it",
        read_totals("**Someone levelled up Mining to 70**```c\n"
                    "Total Mining XP: 737,627``````c\n"
                    "Skill of the Week - Current Mining XP: 12,345```"),
        [("Mining", 70, 737627)])

    print("\nnothing is invented")
    check("an empty message yields nothing", read_totals(""), [])
    check("None yields nothing", read_totals(None), [])
    check("a Dink drop states no lifetime total",
          read_totals("**Someone got 1x Dragon nails from Frost dragon**```c\n"
                      "Value: 568,347 gp```"), [])
    check("chat is not a stat line", read_totals("Pog"), [])

    print("\nbosses and minigames state the total in the TITLE")
    check(
        "a kill count comes from the title, not the delta beside it",
        activities("**Someone has killed Vardorvis 84 times**```c\n"
                   "New kills logged: 6 | Current rank: 147,117```"),
        [("Vardorvis", 84)])
    check(
        "'at least' wording still yields the number",
        activities("**Someone has killed Zulrah at least 1,000 times**```c\n"
                   "New kills logged: 3 | Current rank: 12,004```"),
        [("Zulrah", 1000)])
    check(
        "completions read the same way",
        activities("**Someone has completed Theatre of Blood 244 times**```c\n"
                   "New completions logged: 1 | Current rank: 900```"),
        [("Theatre of Blood", 244)])
    check(
        "a first appearance takes its count from the block",
        activities("**Someone killed Vardorvis enough times to be on the "
                   "hiscores!**```c\nTotal kill count: 1 | Current rank: --```"),
        [("Vardorvis", 1)])
    check(
        "progress lines count too",
        activities("**Someone has progressed Collections Logged 267 times**```c\n"
                   "New collections logged: 2 | Current rank: --```"),
        [("Collections Logged", 267)])
    check(
        "a named total describes itself",
        activities("**Someone has killed Barrows Chests 512 times**```c\n"
                   "Total Barrows Chests count: 512```"),
        [("Barrows Chests", 512)])
    check(
        "a longer activity name is not mistaken for the shorter one",
        activities("**Someone has completed Chambers of Xeric: Challenge Mode "
                   "40 times**```c\nNew completions logged: 1```"),
        [("Chambers of Xeric: Challenge Mode", 40)])
    check(
        "clue tiers from the title",
        activities("**Someone has completed at least 100 Hard Clue Scrolls**"),
        [("Clue Scrolls (hard)", 100)])
    check(
        "clue counts from the block, per tier and overall",
        activities("**Someone has completed 14 Beginner Clue Scrolls**```c\n"
                   "Beginner clues completed: 14 | Total clues completed: 254```"),
        [("Clue Scrolls (beginner)", 14), ("Clue Scrolls (all)", 254)])

    print("\nDELTAS AND WEEKLY ACCUMULATORS ARE NOT TOTALS")
    check(
        "Boss of the Week is ignored, like its skill counterpart",
        activities("```c\nBoss of the Week - Current Zulrah kills: 1```"),
        [])
    check(
        "a bare delta yields nothing at all",
        activities("```c\nNew kills logged: 6 | Current rank: 147,117```"),
        [])
    check(
        "a rank is not a score",
        activities("```c\nCurrent rank: 147,117```"),
        [])
    check(
        "an unknown boss is skipped rather than guessed",
        activities("**Someone has killed Some New Boss 5 times**"),
        [])

    print("\nattribution")
    # Invented names. The pair that matters is one being a prefix of the other,
    # which is a real shape in this data: people register a second account by
    # appending a digit, and matching the shorter name first would file every
    # one of the alt's events under the main.
    names = ["amber quill", "amber quill2", "brass lantern", "copperkettle"]
    index = {
        "by_name": {name: i + 1 for i, name in enumerate(names)},
        "ordered": sorted(names, key=len, reverse=True),
    }
    check("a title names its player",
          title_owner("**Brass Lantern levelled up Mining to 70**", index), 3)
    check("a longer name wins over one that is a prefix of it",
          title_owner("**Amber Quill2 levelled up Mining to 70**", index), 2)
    check("the shorter name still matches on its own",
          title_owner("**Amber Quill levelled up Mining to 70**", index), 1)
    check("a footer names nobody",
          title_owner("```c\nTotal level: 977 | Total Overall XP: 3,358,189```",
                      index), None)
    check("an unknown name is nobody",
          title_owner("**Stranger levelled up Mining to 70**", index), None)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("HISTORY BACKFILL PARSER OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

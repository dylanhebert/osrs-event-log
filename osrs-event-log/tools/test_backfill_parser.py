"""The Discord backfill parser, offline.

Exercises the message shapes PlayerUpdate.py actually produces, plus some
deliberately awkward ones, without any network or database. Message formats
have drifted over the years, so the point here is that the parser survives
shapes it has not seen rather than that it recognises every phrase.

    python tools/test_backfill_parser.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# Import the script's helpers without executing main() or opening a database.
_script = os.path.join(HERE, "backfill_events_from_discord.py")
_source = open(_script, encoding="utf-8").read().replace(
    "from data import repo", "repo = None")
_ns = {"__name__": "_backfill_under_test", "__file__": _script}
exec(compile(_source, "backfill_events_from_discord.py", "exec"), _ns)

split_units = _ns["split_units"]
classify = _ns["classify"]
attribute = _ns["attribute"]

INDEX = {"rune putter": 1, "green donut": 2, "iron putter": 3, "smg 2": 4,
         "green": 9}
BY_LENGTH = sorted(INDEX, key=len, reverse=True)

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    print(f"  {'ok  ' if condition else 'FAIL'} {label}"
          f"{'' if condition or not detail else '  -- ' + detail}")


def parse(content):
    units, leftover = split_units(content)
    owner = None
    for title, _ in units:
        owner = attribute(title, BY_LENGTH, INDEX)
        if owner:
            break
    return units, leftover, owner


def main():
    print("real shapes from PlayerUpdate.py")

    units, leftover, owner = parse(
        "**Rune Putter levelled up Sailing to 30**```c\n428 XP gained | "
        "Total Sailing XP: 13,489``````c\nTotal level: 978 | Total Overall XP: "
        "3,359,525``` <@&123> <@456>")
    check("a level-up plus overall footer splits into 2 units", len(units) == 2,
          f"got {len(units)}")
    check("...attributed to the right player", owner == 1)
    check("...mentions stripped", "<@" not in units[-1][1])
    check("...first is LEVEL", classify(*units[0]) == ("hiscores", "LEVEL"))
    check("...second is OVERALL", classify(*units[1]) == ("hiscores", "OVERALL"))

    units, leftover, owner = parse(
        "**Iron Putter levelled up Fletching to 55**```c\n109,350 XP gained | "
        "Total Fletching XP: 1,114,699```**Iron Putter levelled up Crafting to "
        "42**```c\n10,305 XP gained | Total Crafting XP: 48,742``````c\n"
        "Total level: 981 | Total Overall XP: 6,186,042```<@&1> <@2>")
    check("two concatenated updates plus a footer give 3 units", len(units) == 3,
          f"got {len(units)}")
    check("...all attributed to one player", owner == 3)
    check("...no leftover", leftover == "", repr(leftover))

    units, _, owner = parse(
        "**Green Donut levelled up Sailing to 1**```This is the first time "
        "this skill is on the Hiscores```")
    check("a code block with no language tag still parses", len(units) == 1)
    check("...FIRST is recognised", classify(*units[0]) == ("hiscores", "FIRST"))

    units, _, owner = parse(
        "**Green Donut HAS MAXED!!** \U0001F44F \n*Now you can finally play "
        "the game.*```c\nOverall XP: 4,600,000,000 | Overall rank: 1```")
    check("text between the bold and the block does not break the unit",
          len(units) == 1)
    check("...MAXED is recognised", classify(*units[0]) == ("hiscores", "MAXED"))
    check("...attributed", owner == 2)

    units, _, owner = parse(
        "**Smg 2 killed Zulrah for the first time! bad snek.**```c\n"
        "Total kill count: 1 | Current rank: 120,000```")
    check("a name containing a digit attributes", owner == 4)
    check("...FIRST beats KC in the hint order", classify(*units[0]) == ("hiscores", "FIRST"))

    units, _, owner = parse(
        "**Rune Putter levelled up Mining to 70**```c\n5,000 XP gained | Total "
        "Mining XP: 737,627``````c\nSkill of the Week - Current Mining XP: 12,345```")
    check("a SOTW footer is its own unit", len(units) == 2)
    check("...classified SOTW", classify(*units[1]) == ("hiscores", "SOTW"))

    print("\nrobustness: shapes the parser has not been taught")

    units, leftover, owner = parse(
        "**Some Rando levelled up Attack to 50**```c\n1 XP gained```")
    check("an unknown player yields no owner", owner is None)
    check("...but the unit still parsed, so it is reported not crashed",
          len(units) == 1)

    units, leftover, owner = parse("**Rune Putter did something brand new**")
    check("a bold line with no code block yields no unit", len(units) == 0)
    check("...and is surfaced as leftover rather than lost", leftover != "",
          repr(leftover))

    units, _, _ = parse("plain text nobody expected")
    check("plain prose yields no units", len(units) == 0)

    units, _, _ = parse("")
    check("empty content is handled", len(units) == 0)

    units, _, owner = parse(
        "**Rune Putter reached a thing nobody coded a phrase for**```c\nx```")
    check("unrecognised wording still parses", len(units) == 1)
    # Neither side's markers appear, so the honest answer is that the source
    # is unknown rather than a guess at hiscores.
    check("...and reports an unknown source rather than guessing",
          classify(*units[0]) == ("unknown", "UPDATE"))
    check("...still attributed to the player", owner == 1)

    print("\nname matching")
    check("a longer name wins over a shorter prefix",
          attribute("Green Donut levelled up Attack to 2", BY_LENGTH, INDEX) == 2)
    check("the shorter name still matches on its own",
          attribute("Green levelled up Attack to 2", BY_LENGTH, INDEX) == 9)
    check("a name is not matched mid-word",
          attribute("Greenish levelled up Attack to 2", BY_LENGTH, INDEX) is None)
    check("an empty title matches nobody",
          attribute("", BY_LENGTH, INDEX) is None)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for label in FAILED:
            print("  -", label)
        return 1
    print("BACKFILL PARSER OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

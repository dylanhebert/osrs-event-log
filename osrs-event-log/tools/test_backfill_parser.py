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
looks_like_event_header = _ns["looks_like_event_header"]
ROLE_MENTION = _ns["ROLE_MENTION"]

INDEX = {"zezima alt": 1, "woox major": 2, "hey jase": 3, "alt 2": 4,
         "zezima": 9}
BY_LENGTH = sorted(INDEX, key=len, reverse=True)

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    print(f"  {'ok  ' if condition else 'FAIL'} {label}"
          f"{'' if condition or not detail else '  -- ' + detail}")


def parse(content):
    # Bare bold is only an event when it starts with a known player, which is
    # what the real caller passes too.
    units, leftover = split_units(
        content,
        accept_bare_bold=lambda t: looks_like_event_header(t, BY_LENGTH))
    owner = None
    for title, _ in units:
        owner = attribute(title, BY_LENGTH, INDEX)
        if owner:
            break
    return units, leftover, owner


def kind_of(content, index=0):
    """(source, event_type) the real caller would store, milestone applied.

    Milestone is decided by the ROLE mention, not by wording, and the caller
    promotes hiscores units to MILESTONE when it is present. Dink keeps its
    payload type either way.
    """
    units, _, _ = parse(content)
    source, kind = classify(*units[index])
    if ROLE_MENTION.search(content) and source == "hiscores":
        kind = "MILESTONE"
    return source, kind


def is_milestone(content):
    return bool(ROLE_MENTION.search(content))


def main():
    print("real shapes from PlayerUpdate.py")

    units, leftover, owner = parse(
        "**Zezima Alt levelled up Sailing to 30**```c\n428 XP gained | "
        "Total Sailing XP: 13,489``````c\nTotal level: 978 | Total Overall XP: "
        "3,359,525``` <@&123> <@456>")
    check("a level-up plus overall footer splits into 2 units", len(units) == 2,
          f"got {len(units)}")
    check("...attributed to the right player", owner == 1)
    check("...mentions stripped", "<@" not in units[-1][1])
    check("...first is a SKILL update", classify(*units[0]) == ("hiscores", "SKILL"))
    check("...second is OVERALL", classify(*units[1]) == ("hiscores", "OVERALL"))

    units, leftover, owner = parse(
        "**Hey Jase levelled up Fletching to 55**```c\n109,350 XP gained | "
        "Total Fletching XP: 1,114,699```**Hey Jase levelled up Crafting to "
        "42**```c\n10,305 XP gained | Total Crafting XP: 48,742``````c\n"
        "Total level: 981 | Total Overall XP: 6,186,042```<@&1> <@2>")
    check("two concatenated updates plus a footer give 3 units", len(units) == 3,
          f"got {len(units)}")
    check("...all attributed to one player", owner == 3)
    check("...no leftover", leftover == "", repr(leftover))

    units, _, owner = parse(
        "**Woox Major levelled up Sailing to 1**```This is the first time "
        "this skill is on the Hiscores```")
    check("a code block with no language tag still parses", len(units) == 1)
    check("...first-time-on-hiscores is a SKILL update",
          classify(*units[0]) == ("hiscores", "SKILL"))

    units, _, owner = parse(
        "**Woox Major HAS MAXED!!** \U0001F44F \n*Now you can finally play "
        "the game.*```c\nOverall XP: 4,600,000,000 | Overall rank: 1```")
    check("text between the bold and the block does not break the unit",
          len(units) == 1)
    check("...MAXED is a hiscores unit; milestone comes from the role mention",
          classify(*units[0]) == ("hiscores", "SKILL"))
    check("...attributed", owner == 2)

    units, _, owner = parse(
        "**Alt 2 killed Zulrah for the first time! bad snek.**```c\n"
        "Total kill count: 1 | Current rank: 120,000```")
    check("a name containing a digit attributes", owner == 4)
    check("...a boss first kill is a MINIGAME update",
          classify(*units[0]) == ("hiscores", "MINIGAME"))

    units, _, owner = parse(
        "**Zezima Alt levelled up Mining to 70**```c\n5,000 XP gained | Total "
        "Mining XP: 737,627``````c\nSkill of the Week - Current Mining XP: 12,345```")
    check("a SOTW footer is its own unit", len(units) == 2)
    check("...classified SOTW", classify(*units[1]) == ("hiscores", "SOTW"))

    print("\nrobustness: shapes the parser has not been taught")

    units, leftover, owner = parse(
        "**Some Rando levelled up Attack to 50**```c\n1 XP gained```")
    check("an unknown player yields no owner", owner is None)
    check("...but the unit still parsed, so it is reported not crashed",
          len(units) == 1)

    # Ten of the thirteen Dink formatters `return header` with no code block at
    # all when the payload carried no stats to show, so a bold line on its own
    # is a real event rather than a parse failure.
    units, leftover, owner = parse("**Zezima Alt just received Herbi!**")
    check("a bold line with no code block is still a unit", len(units) == 1,
          f"got {len(units)}")
    check("...attributed", owner == 1)
    check("...and classified from the header alone",
          classify(*units[0]) == ("dink", "PET"))
    check("...leaving nothing over", leftover == "", repr(leftover))

    units, _, _ = parse("plain text nobody expected")
    check("plain prose yields no units", len(units) == 0)

    units, _, _ = parse("")
    check("empty content is handled", len(units) == 0)

    units, _, owner = parse(
        "**Zezima Alt reached a thing nobody coded a phrase for**```c\nx```")
    check("unrecognised wording still parses", len(units) == 1)
    # Neither side's markers appear, so the honest answer is that the source
    # is unknown rather than a guess at hiscores.
    check("...and reports an unknown source rather than guessing",
          classify(*units[0]) == ("unknown", "UPDATE"))
    check("...still attributed to the player", owner == 1)

    print("\nolder formats, found by sweeping six years of real history")

    # Mentions used to lead the message on their own bold line. Left alone that
    # line becomes the unit's title, which loses the real one AND stores a raw
    # Discord member id in the message text.
    units, _, owner = parse(
        "**~ <@111122223333444455> ~**\n"
        "**Zezima Alt levelled up Hunter to 97. So close.**```c\n"
        "4,800 XP gained | Total Hunter XP: 10,000```")
    check("a leading mention line does not become the title", len(units) == 1,
          f"got {len(units)}")
    check("...the real title is used instead",
          classify(*units[0]) == ("hiscores", "SKILL"))
    check("...attributed to the player, not lost", owner == 1)
    check("...and no Discord id survives into the stored text",
          "<@" not in units[0][1])

    units, _, owner = parse(
        "**~ <@&555566667777888899> somebody ~**\n"
        "**Zezima Alt has achieved 110,000,000 Strength XP**```c\n"
        "369,915 XP gained | Total Strength XP: 110,000,000```")
    check("a role mention with a trailing name is also stripped",
          "<@" not in units[0][1] and owner == 1)

    # An older format emitted the header alone, with no code block, so there is
    # no body for a marker to live in.
    units, _, owner = parse(
        "**Zezima Alt has killed Abyssal Sire at least 500 times**")
    check("bold-only hiscores is recognised as hiscores, not dink",
          classify(*units[0])[0] == "hiscores",
          str(classify(*units[0])))

    units, _, owner = parse(
        "**Zezima Alt completed Chambers of Xeric enough times to be on the "
        "hiscores!**")
    check("...even when the wording reads like a Dink quest completion",
          classify(*units[0])[0] == "hiscores", str(classify(*units[0])))

    print("\nmilestones: the role mention, not the wording")
    # post_update sends milestones as f'{...}{mention_role} {mention_member}'
    # and routine updates as f'{...}{mention_member}'. The ROLE mention is the
    # only difference, and it is the same signal ;milestones keys on.
    role_ping = ("**Zezima Alt levelled up Attack to 99**```c\n"
                 "1 XP gained | Total Attack XP: 13,034,431``` <@&123> <@456>")
    member_only = ("**Zezima Alt levelled up Mining to 70**```c\n"
                   "5,000 XP gained | Total Mining XP: 737,627``` <@456>")
    check("a role mention marks a milestone", is_milestone(role_ping))
    check("...and it is stored as MILESTONE",
          kind_of(role_ping) == ("hiscores", "MILESTONE"))
    check("a member mention alone is a routine update",
          not is_milestone(member_only))
    check("...and stays SKILL", kind_of(member_only) == ("hiscores", "SKILL"))

    here_ping = ("**Zezima Alt levelled up Attack to 99**```c\n"
                 "1 XP gained | Total Attack XP: 13,034,431``` @here <@456>")
    check("@here counts, since it is the fallback when no role is set",
          is_milestone(here_ping))

    old_ping = ("**~ <@&123> ~**\n**Zezima Alt has achieved 100,000,000 "
                "Strength XP**```c\n1 XP gained | Total Strength XP: 100,000,000```")
    check("the old leading-mention format is detected too",
          is_milestone(old_ping) and kind_of(old_ping) == ("hiscores", "MILESTONE"))

    # THE CASE THAT MAKES is_milestone A COLUMN RATHER THAN AN event_type.
    pet = ("**Zezima Alt just received Herbi!**```c\n"
           "Milestone: 12,875,356``` <@&123> <@456>")
    check("a Dink pet pings the role, so it IS a milestone", is_milestone(pet))
    check("...but keeps its PET type rather than becoming MILESTONE",
          kind_of(pet) == ("dink", "PET"))

    collection = ("**Zezima Alt added Shark paint to their Collection Log**"
                  "```c\nEntries: 31/1712 | Price: 5,400 gp``` <@456>")
    check("a Dink collection entry does not ping, so it is not a milestone",
          not is_milestone(collection))
    check("...and keeps its type", kind_of(collection) == ("dink", "COLLECTION"))

    print("\nname matching")
    check("a longer name wins over a shorter prefix",
          attribute("Woox Major levelled up Attack to 2", BY_LENGTH, INDEX) == 2)
    check("the shorter name still matches on its own",
          attribute("Zezima levelled up Attack to 2", BY_LENGTH, INDEX) == 9)
    check("a name is not matched mid-word",
          attribute("Zezimaish levelled up Attack to 2", BY_LENGTH, INDEX) is None)
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

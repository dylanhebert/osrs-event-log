#!/usr/bin/env python3
"""Owner-only permission check — must fail closed.

    python tools/test_super_user.py

The bot owner's Discord id used to be hardcoded in 14 places across
cogs/cmds/admin.py and cogs/cmds/super.py. It now comes from SUPER_USER_ID in
bot_config.json, which is gitignored because this repo is public.

Moving a permission check into config introduces a failure mode that did not
exist before: a missing or malformed key. The direction it fails in is the whole
point. If an unset SUPER_USER_ID read as "match", every user would gain the
owner-only commands — ;servers, ;message, ;maxplayers — across every server the
bot is in. Denying instead locks the owner out of a handful of commands, which
is recoverable by editing one config value.

Offline: no Discord, no database, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


def main():
    from data.handlers import general
    from data.handlers import helpers as h

    original = h.SUPER_USER_ID
    fails = []

    def check(label, configured, candidate, expected):
        h.SUPER_USER_ID = configured
        got = general.is_super_user(candidate)
        if got is not expected:
            fails.append(f"{label}: expected {expected}, got {got} "
                         f"(SUPER_USER_ID={configured!r}, user={candidate!r})")

    try:
        owner = 111111111111111111
        other = 222222222222222222

        # --- the ordinary cases ---------------------------------------- #
        check("owner matches", owner, FakeUser(owner), True)
        check("someone else does not", owner, FakeUser(other), False)
        check("raw id accepted", owner, owner, True)
        check("raw id mismatch", owner, other, False)
        # Discord ids exceed 2^53, so a config file that quotes them must not
        # silently stop matching.
        check("id as string in config", str(owner), FakeUser(owner), True)
        check("id as string on user", owner, FakeUser(str(owner)), True)

        # --- fail closed ------------------------------------------------- #
        check("unset denies the owner", None, FakeUser(owner), False)
        check("unset denies everyone", None, FakeUser(other), False)
        check("unset denies a raw id", None, owner, False)
        check("empty string denies", "", FakeUser(owner), False)
        check("malformed config denies", "not-an-id", FakeUser(owner), False)
        check("malformed user denies", owner, FakeUser(None), False)
        check("None user denies", owner, None, False)

        # A user object with no id attribute must not be treated as the id.
        check("object without id denies", owner, object(), False)
    finally:
        h.SUPER_USER_ID = original

    print("\n" + "=" * 68)
    if fails:
        print(f"  SUPER USER CHECK: FAILED — {len(fails)} case(s)")
        print("=" * 68 + "\n")
        for problem in fails:
            print(f"    {problem}")
        return 1

    print("  SUPER USER CHECK: PASSED")
    print("=" * 68 + "\n")
    print("        6 positive/negative id cases, including quoted ids")
    print("        7 fail-closed cases: unset, empty, malformed, missing")
    print("\n    An unset or broken SUPER_USER_ID denies everyone rather than")
    print("    granting the owner-only commands to every user.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

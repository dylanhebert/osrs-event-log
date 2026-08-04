"""Construct the Bot and load every extension. No token, no network.

Import success is not enough and never was: `import discord` succeeded on Python
3.14 while `commands.Bot(...)` raised "There is no current event loop", which is
what forced the py-cord upgrade during the SQLite migration. The probe that
actually catches problems is to build the Bot and load each entry in
initial_extensions, so a cog that only fails at registration time fails here
instead of on the droplet.

    python tools/test_cog_load.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INNER = os.path.dirname(HERE)
sys.path.insert(0, INNER)

# The bot builds every path from the current directory, so this test has to
# adopt that convention even though nothing else here does.
os.chdir(INNER)

# Kept in step with initial_extensions in osrs-event-log.py. That file is not
# importable as a module (the hyphens make it an invalid identifier) and it
# starts the bot at import, so the list is mirrored rather than imported.
EXTENSIONS = [
    "cogs.cmds.user",
    "cogs.cmds.admin",
    "cogs.cmds.super",
    "cogs.cmds.web",
    "cogs.looper",
    "cogs.dink_webhook",
]


def main():
    import discord
    from discord.ext import commands

    print(f"  python   {sys.version.split()[0]}")
    print(f"  py-cord  {discord.__version__}\n")

    # Cross-check the mirrored list against the real one, so adding a cog to the
    # bot without adding it here cannot leave it untested.
    source = os.path.join(INNER, "osrs-event-log.py")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    declared = [name for name in EXTENSIONS if f"'{name}'" in text or f'"{name}"' in text]
    missing = [name for name in EXTENSIONS if name not in declared]
    if missing:
        print(f"  FAIL these are not in initial_extensions: {missing}")
        return 1

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix=";", intents=intents)
    print("  ok   Bot() constructed")

    failed = []
    for name in EXTENSIONS:
        try:
            bot.load_extension(name)
            print(f"  ok   loaded {name}")
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL {name}: {type(e).__name__}: {e}")

    # The new commands must actually be registered, not merely importable.
    for command in ("webpassword", "webrevoke"):
        registered = bot.get_command(command) is not None
        print(f"  {'ok  ' if registered else 'FAIL'} ;{command} is registered")
        if not registered:
            failed.append((command, "not registered"))

    print()
    if failed:
        print(f"FAILED: {len(failed)}")
        return 1
    print(f"ALL {len(EXTENSIONS)} EXTENSIONS LOADED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

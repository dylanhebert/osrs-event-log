# Data handler helpers
#
# Bot configuration still lives in bot_config.json — it is deployment config,
# not user state, and keeping it a file means it can be edited without touching
# the database. Everything that used to be JSON *state* is now SQLite; see
# data/repo/.

import json
import pathlib

from common.logger import logger


# ------------------ Non-Async Json Read for Specific Things ----------------- #

def db_open_non_async(path):
    """Opens a json file as a python dict/list non-asyncronously"""
    with open(path, "r") as f:
        return json.load(f)


# --------------------------------- Constants -------------------------------- #

# Every path is built from the current working directory, not the module
# location. The service must run from the inner osrs-event-log directory or it
# dies at import. This predates the migration and is unchanged by it.
DIR_PATH = str(pathlib.Path().absolute())

BOT_INFO_ALL = db_open_non_async(DIR_PATH + "/bot_config.json")
BOT_TOKEN = BOT_INFO_ALL['BOT_TOKEN']
MAX_PLAYERS_PER_MEMBER = BOT_INFO_ALL['MAX_PLAYERS_PER_MEMBER']
DINK_BASE_URL = BOT_INFO_ALL['DINK_BASE_URL']
DINK_HOST = BOT_INFO_ALL['DINK_HOST']
DINK_PORT = BOT_INFO_ALL['DINK_PORT']
DINK_TEST_CHANNEL = BOT_INFO_ALL['DINK_TEST_CHANNEL']

DATA_PATH = "data/"
FULL_DATA_PATH = DIR_PATH + "/" + DATA_PATH
MESSAGES_PATH = FULL_DATA_PATH + "custom_messages.json"
SCHEMA_PATH = FULL_DATA_PATH + "schema.sql"
DB_PATH = FULL_DATA_PATH + "osrs.db"

# Retained so a rollback export has somewhere obvious to land, and so the
# migration tooling and these handlers agree on where the old files were.
DB_DISCORD_PATH = FULL_DATA_PATH + "db_discord.json"
DB_RUNESCAPE_PATH = FULL_DATA_PATH + "db_runescape.json"


# ------------------------------ Json Read/Write ----------------------------- #

async def db_open(path):
    """Opens a json file as a python dict/list"""
    with open(path, "r") as f:
        return json.load(f)


async def db_write(path, db):
    """Writes a python dict/list as a json file"""
    with open(path, "w") as f:
        json.dump(db, f, indent=4, sort_keys=False)


# ------------------------------- DB bootstrap ------------------------------- #

def ensure_db():
    """Open the SQLite store, creating it from schema.sql on first run.

    Refuses to create an empty database when the legacy JSON state is still
    sitting next to it, because that combination means the migration has not
    been run yet. Starting the bot in that state would bring it up with zero
    players and zero servers: it would stop posting entirely, and the first
    ;add would begin rebuilding state from nothing on top of live data.

    Deleting or renaming the two JSON files after a verified migration is what
    turns this check off.
    """
    import os

    from data import repo

    if not os.path.exists(DB_PATH):
        legacy = [p for p in (DB_DISCORD_PATH, DB_RUNESCAPE_PATH) if os.path.exists(p)]
        if legacy:
            raise RuntimeError(
                f"{DB_PATH} does not exist but the legacy JSON state does "
                f"({', '.join(os.path.basename(p) for p in legacy)}).\n"
                "Run the migration first:\n"
                "    python tools/migrate_json_to_sqlite.py --db data/osrs.db\n"
                "then verify with tools/test_roundtrip.py and tools/test_zero_delta.py.\n"
                "Starting now would come up with an empty database.")

    return repo.bootstrap(path=DB_PATH, schema_path=SCHEMA_PATH)


def refresh_max_players(new_val):
    global MAX_PLAYERS_PER_MEMBER
    MAX_PLAYERS_PER_MEMBER = new_val
    return MAX_PLAYERS_PER_MEMBER


logger.debug('Data handler helpers loaded.')

# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer. Every function here keeps the exact signature the cogs already
# call — including taking discord.py Server/Member objects — and forwards to
# data/repo, which deals only in plain ids. The cogs are unchanged by the SQLite
# migration; that is the point of the split.

from common.logger import logger
from common import exceptions as ex
from data import repo
from . import helpers as h


# ----------------------------- SIMPLE GET THINGS ---------------------------- #

def get_bot_token():
    return h.BOT_TOKEN

def get_dink_base_url():
    return h.DINK_BASE_URL

def get_dink_host():
    return h.DINK_HOST

def get_dink_port():
    return h.DINK_PORT

def get_dink_test_channel():
    return h.DINK_TEST_CHANNEL

def get_custom_messages():
    return h.db_open_non_async(h.MESSAGES_PATH)


# ------------------------------- Verify Files ------------------------------- #

def verify_files(file_name=None):
    """Make sure the data store exists and is usable.

    Kept as verify_files() with an optional argument because osrs-event-log.py
    calls it twice at startup, once per old JSON filename. Creating the database
    is idempotent, so the second call is a no-op.
    """
    connection = h.ensure_db()
    logger.debug(f'Data store ready at {h.DB_PATH}')
    return connection


# ----------------------- Update Max Players Per Member ---------------------- #

async def update_max_players(new_val):
    """Updates max OSRS accounts per Discord member"""
    config_path = h.DIR_PATH + "/bot_config.json"
    try:
        config_all = await h.db_open(config_path)
        logger.debug(f'Old max players: {config_all["MAX_PLAYERS_PER_MEMBER"]}')
        config_all['MAX_PLAYERS_PER_MEMBER'] = new_val
        await h.db_write(config_path, config_all)
        h.refresh_max_players(new_val)
    except Exception:
        raise ex.DataHandlerError('COULD NOT LOAD BOT CONFIG!')


async def is_dinklink_in_use(dinklink):
    return repo.players.dink_key_in_use(dinklink)


def dink_link_full_url(dinklink):
    return f"{h.DINK_BASE_URL}/dink/{dinklink}"

# Member = A Discord member
# Player = A Runescape account

import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h


# ----------------------------- Get Member Entry ----------------------------- #

async def get_member_entry(Server, Member, entry):
    """Get and return member entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET MEMBER ENTRY - Member: {Member.name} | ID: {Member.id} | Entry: {entry}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    try: return db[f'member:{Member.id}#server:{Server.id}#{entry}']
    except KeyError:
        raise ex.DataHandlerError(f'Could not find {entry} for {Member.name}')

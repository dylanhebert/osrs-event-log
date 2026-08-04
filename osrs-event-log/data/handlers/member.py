# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer — see general.py. Signatures unchanged; storage is data/repo.

from common.logger import logger
from common import exceptions as ex
from data import repo


# ----------------------------- Get Member Entry ----------------------------- #

async def get_member_entry(Server, Member, entry):
    """Get and return member entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET MEMBER ENTRY - Member: {Member.name} | ID: {Member.id} | Entry: {entry}')
    if entry != 'players':
        raise ex.DataHandlerError(f'Could not find {entry} for {Member.name}')
    players = repo.players.member_players(Server.id, Member.id)
    if not players:
        # The JSON version raised when the key was absent, and the caller shows
        # this text to the user, so the empty case has to keep raising.
        raise ex.DataHandlerError(f'Could not find {entry} for {Member.name}')
    return players

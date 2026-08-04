from common.logger import logger
from data import repo


class DinkPlayerHandler:
    """Per-request state for the Dink webhook.

    Dink does not retry, so anything that raises here loses an event
    permanently. build_cache() is now a cheap refresh rather than a 320 KB
    json.load() on every incoming webhook.
    """

    def __init__(self):
        self.server_info_all = None

    async def build_cache(self):
        self.server_info_all = await self.get_server_info_all()

    async def remove_cache(self):
        self.server_info_all = None

    async def get_server_info_all(self):
        return repo.servers.info_all(active_only=True)

    async def get_all_player_info(self, rs_name):
        """Gets all servers and members connected to a player"""
        logger.debug('------------------------------')
        logger.debug(f'Initialized DINK GET PLAYER INFO - Player: {rs_name}')
        player_servers_all = repo.players.active_links(rs_name)
        logger.debug(f"Finished DINK GET PLAYER INFO - Player: {rs_name}")
        return player_servers_all

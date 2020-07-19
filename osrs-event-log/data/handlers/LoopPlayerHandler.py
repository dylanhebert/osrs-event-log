import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h


class LoopPlayerHandler:
    def __init__(self):
        self.data_discord = None
        self.data_runescape = None
        self.server_info_all = None
        
    async def build_cache(self):
        self.data_discord = await h.db_open(h.DB_DISCORD_PATH)
        self.data_runescape = await h.db_open(h.DB_RUNESCAPE_PATH)
        self.server_info_all = await self.get_server_info_all()
        
    async def remove_cache(self):
        # Write new player info to Db before clear
        await h.db_write(h.DB_RUNESCAPE_PATH, self.data_runescape)
        self.data_discord = None
        self.data_runescape = None
        self.server_info_all = None
        
    async def get_server_info_all(self):
        build_dict = {}
        for server in self.data_discord['active_servers']:
            build_dict[str(server)] = {
                'channel': self.data_discord[f'server:{server}#channel'],
                'role': self.data_discord[f'server:{server}#role'] }
        return build_dict

        
    async def get_all_player_info(self, rs_name):
        """Gets all servers and members connected to a player"""
        logger.info('------------------------------')
        logger.info(f'Initialized GET PLAYER LOOPER INFO - Player: {rs_name}')
        # Loop through db to get player's servers
        player_servers_all = []
        for server in self.data_discord[f'player:{rs_name}#all_servers']:
            logger.debug(f'Checking server: {server}')
            if server in self.data_discord['active_servers']:
                player_servers_all.append({
                    "server": server,
                    "member": self.data_discord[f'player:{rs_name}#server:{server}#member'],
                    "mention": self.data_discord[f'player:{rs_name}#server:{server}#mention']
                })
        logger.info(f"Finished GET PLAYER LOOPER INFO - Player: {rs_name}")
        # logger.debug(player_servers_all)
        return player_servers_all


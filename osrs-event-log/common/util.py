# OSRS Activity Log Bot: util.py
# - Utilities & functions commonly used throughout the bot
#

import asyncio
import aiohttp
from common.logger import logger
import pathlib
import discord
import secrets

# --- VARIABLES ---
# paths to json files
dir_path = str(pathlib.Path().absolute())
servers_path = dir_path + "/data/servers.json"
players_path = dir_path + "/data/players.json"
messages_path = dir_path + "/data/custom_messages.json"

# Timeout for access a player hiscore page
TIMEOUT = aiohttp.ClientTimeout(total=15)

# HISCORES ENDPOINT (before username)
# The human-facing hiscorepersonal page is served behind bot protection that
# returns 403 to datacenter IPs, so it stopped working when the bot moved from
# a home Raspberry Pi to the droplet. index_lite.json is the official
# machine-readable endpoint and is not blocked. It also removes the need to
# scrape HTML with BeautifulSoup.
HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player="


# ------- NON-ASYNC FUNCTIONS -------
#------------------------------------

# FORMAT NAME: DISCORD -> RS
def name_to_rs(name):
    if ' ' in name:
        name = name.replace(' ', '+')
        return name.title()
    else:
        return name.title()

# FORMAT NAME: RS -> DISCORD
def name_to_discord(name):
    if '+' in name:
        name = name.title().replace('+', ' ')
        return name
    else:
        name = name.title()
        return name

# MINUTES CONVERTER
async def time_mins(secs):
    minutes = secs * 60
    return minutes

# COMPARE OLD VS NEW XP
def xp_changed(old, new):
    if old != new:
        return True
    else:
        return False

# FORMAT COMMAS IN LONG INTS
def format_int(num):
    if num is None:
        return 0
    if "," in num:
        num = int(num.replace(",", ""))
    else:
        num = int(num)
    return num

# FORMAT COMMAS IN LONG INTS #2
def format_int_str(num):
    try:
        num = int(num)
    except (ValueError, TypeError):
        return str(num)  # fallback to string if it can't be converted
    if num >= 1000:
        return "{:,}".format(num)
    else:
        return str(num)


# ------ BASIC ASYNC FUNCTIONS ------
#------------------------------------

# CHECK IF A MEMBER IS ADMIN
async def is_admin(mem):
    if mem.guild_permissions.administrator == True:
        return True
    else:
        return False

# CHECK IF A RS PLAYER IS ACCEPTABLE
async def check_player_validity(name):
    page = await get_page(name)
    if page != None:
        try:
            logger.debug(f"{name} has a valid hiscores page!")
            player_dict = await get_player_scores(name, page)
            return player_dict
        except Exception as e:
            logger.exception(f'Unable to parse player hiscores: {name} | {e}')
            return None
    else:
        logger.info(f'Unable to get player: {name} | Page status: None')
        return None


# ------- WEB FUNCTIONS -------
#------------------------------

# FORMAT A HISCORES NUMBER THE WAY THE OLD HTML PAGE DID
def hiscore_value(num):
    """The scraped page rendered every number with thousands separators, and an
    unranked entry as '--'. The stored player database is full of those strings,
    so index_lite.json's raw ints have to be formatted back into the identical
    shape. If they are not, every skill of every player compares as changed on
    the first run and the bot spams a milestone message for all of them."""
    if num is None or num == -1:
        return '--'
    return "{:,}".format(num)


# REQUEST HISCORES DATA (AIOHTTP)
async def get_page(name):
    """Returns the decoded index_lite.json payload for a player, or None if the
    player could not be fetched. A player who does not exist returns 404, which
    lands in the same None branch as a network failure."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.get(HISCORES_URL + name) as p:
                    if p.status == 200:
                        # Jagex serves this as text/html, so aiohttp's content
                        # type check has to be disabled to decode it as json.
                        page = await p.json(content_type=None)
                        logger.debug(f'{name}: Fetched hiscores with aiohttp...')
                    else:
                        logger.info(f'Unable to get page for {name} | Page status: {p.status}')
                        page = None
            except asyncio.TimeoutError as e:
                page = None
                logger.exception(f'{name}: Timeout getting async session, returning None for page')
    except Exception as e:
        page = None
        logger.exception(f'{name}: aiohttp failed, returning None for page')
    return page


# GET A PLAYERS SCORES INTO DICT
async def get_player_scores(name_rs, page):
    """Normalises an index_lite.json payload into the same structure the scraped
    page produced: {'skills': {name: {rank, level, xp}}, 'minigames': {name: {rank, score}}}."""
    logger.debug(f'{name_rs}: got page...')
    # new player dict to fill and return to correct discord id
    player_dict = {
        'skills' : {},
        'minigames': {}
    }
    # check if player has no hiscore profile
    if not page or not page.get('skills'):
        logger.debug(f"{name_rs} not found! Appended empty player_dict.")
        return player_dict
    # player has hiscore profile
    logger.debug(f"{name_rs}: found player...")
    for skill in page['skills']:
        # The page listed only skills the player actually had xp in, and dropped
        # the rest of the row entirely — including Overall, for an account that
        # has fallen off the hiscores altogether. index_lite instead returns all
        # 25 every time with -1 in the gaps. Mirror the page: without this, an
        # unranked skill reaches PlayerUpdate as '--' and format_int() raises
        # ValueError: invalid literal for int() with base 10: '--'.
        if skill.get('xp', 0) <= 0:
            continue
        player_dict['skills'][skill['name']] = {
            'rank': hiscore_value(skill.get('rank')),
            'level': hiscore_value(skill.get('level')),
            'xp': hiscore_value(skill.get('xp')),
        }
    for activity in page.get('activities', []):
        # The old page only listed activities the player had actually done, so
        # anything with no score is skipped to keep the stored keys identical.
        # index_lite.json instead returns all 90-odd of them every time.
        if activity.get('score', 0) <= 0:
            continue
        player_dict['minigames'][activity['name']] = {
            'rank': hiscore_value(activity.get('rank')),
            'score': hiscore_value(activity.get('score')),
        }
    logger.debug(f"{name_rs}: Successfully created dict for {name_rs}!")
    return player_dict


async def message_server(Server, serv_dict, message, mention):
    """ Needs dict:\n
    {
        "id": [guild.id],
        "channel": [channel.id] or None,
        "role": [role.id] or None
    }
    """
    try:
        # If not channel in this server then skip server
        if serv_dict["channel"]:
            rs_chan = Server.get_channel(serv_dict["channel"])
            # Get mention role, if not then use @here, empty if not mentioning
            rs_role_men = ''
            if mention:
                if serv_dict["role"]:
                    rs_role = Server.get_role(serv_dict["role"])
                    rs_role_men = rs_role.mention # CHANGE FOR TESTING
                else:
                    rs_role_men = "@here"
            # Send message!
            await rs_chan.send(f'{message}\n{rs_role_men}')
            logger.info(f"Sent message in guild id: {serv_dict['id']} | name: {Server.name} | channel: {rs_chan.name} | Mention: {mention}")
        else:
            logger.info(f"Could not send message in guild id: {serv_dict['id']} -- No channel specified")
    except Exception as e:
        logger.exception(f"Could not send message in guild id: {serv_dict['id']} -- {e}")


async def message_all_servers(bot, all_servers, message, mention):
    for serv_dict in all_servers:
        Server = bot.get_guild(serv_dict['id'])
        await message_server(Server, serv_dict, message, mention)
        
        
async def message_separate_servers(bot, servers_messages, mention):
    for serv_dict in servers_messages['all_servers']:
        Server = bot.get_guild(serv_dict['id'])
        message = servers_messages['all_messages'][str(serv_dict['id'])]
        await message_server(Server, serv_dict, message, mention)


async def message_specific_server(bot, Server, all_servers, message, mention):
    for serv_dict in all_servers:
        if Server.id == serv_dict['id']:
            await message_server(Server, serv_dict, message, mention)
        

def generate_dink_link():
    key = secrets.token_urlsafe(16)  # URL-safe, reasonably short
    return key
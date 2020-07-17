# OSRS Activity Log Bot: util.py
# - Utilities & functions commonly used throughout the bot
#

import asyncio
import aiohttp
from common.logger import logger
from bs4 import BeautifulSoup
import pathlib

# --- VARIABLES ---
# paths to json files
dir_path = str(pathlib.Path().absolute())
servers_path = dir_path + "/data/servers.json"
players_path = dir_path + "/data/players.json"
messages_path = dir_path + "/data/custom_messages.json"

# Timeout for access a player hiscore page
TIMEOUT = aiohttp.ClientTimeout(total=15)

# HISCORES PAGE (before username)
HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool/hiscorepersonal?user1="


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
    if "," in num:
        num = int(num.replace(",", ""))
    else:
        num = int(num)
    return num

# FORMAT COMMAS IN LONG INTS #2
def format_int_str(num):
    if len(str(num)) >= 4:
        num = "{:,}".format(num)
    else:
        num = str(num)
    return num


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
            logger.info(f"{name} has a valid hiscores page!")
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

# REQUEST WEB PAGE (AIOHTTP)
async def getPage(name):
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.get(HISCORES_URL + name) as p:
                    if p.status == 200:
                        page = await p.text()
                        logger.debug(f'{name}: Scraped page with aiohttp...')
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
    parse_minigames = False
    logger.debug(f'{name_rs}: got page...')
    soup = BeautifulSoup( page, 'html.parser' )
    logger.debug(f'{name_rs}: got soup...')
    scores = soup.find(id="contentHiscores")
    logger.debug(f'{name_rs}: got scores...')
    # new player dict to fill and return to correct discord id
    player_dict = {
        'skills' : {},
        'minigames': {}
    }
    # check if player has no hiscore profile
    logger.debug(f'{name_rs}: contents[1]: '+scores.contents[1].name)
    if scores.contents[1].name != 'table':  # if there's no table, the player has no scores
        logger.info(f"{name_rs} not found! Appended empty player_dict.")
        return player_dict
    # player has hiscore profile
    logger.debug(f"{name_rs}: found player...")
    for tr in scores.find_all('tr')[3:]:
        if 'Minigame' in tr.get_text():
            parse_minigames = True
            continue
        row_entry = tr.find_all('td')
        skill = row_entry[1].get_text().strip()
        skill_dict = {}
        skill_dict['rank'] = row_entry[2].get_text()
        if not parse_minigames:
            skill_dict['level'] = row_entry[3].get_text()
            skill_dict['xp'] = row_entry[4].get_text()
            player_dict['skills'][skill] = skill_dict  # update skill to skills dict
        else:
            skill_dict['score'] = row_entry[3].get_text()
            player_dict['minigames'][skill] = skill_dict  # update clue/boss to minigames dict
    logger.info(f"{name_rs}: Successfully created dict for {name_rs}!")
    return player_dict

# OSRS Activity Log Bot: util.py
# - Utilities & functions commonly used throughout the bot
#

import discord
from discord.ext import commands
import time
import asyncio
import aiohttp
import json
from common.logger import logger
from bs4 import BeautifulSoup
import pathlib

# --- VARIABLES ---
# paths to json files
dir_path = str(pathlib.Path().absolute())
servers_path = dir_path + "/data/servers.json"
players_path = dir_path + "/data/players.json"
messages_path = dir_path + "/data/custom_messages.json"

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
async def get_page(name):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(HISCORES_URL + name) as p:
                if p.status == 200:
                    page = await p.text()
                else:
                    logger.info(f'Unable to get page for {name} | Page status: {p.status}')
                    page = None
    except Exception as e:
        page = None
        logger.exception(f'aiohttp failed, returning None for page: {e}')
    logger.debug('scraped page with aiohttp...')
    return page


# # REQUEST WEB PAGE (REQUESTS) (OLD)
# async def getPageRequests(url, name):
#     try:
#         page = requests.get(url + name)
#     except:
#         page = None
#         logger.debug('requests.get failed! Returning None')
#     logger.debug('scraped...')
#     # page.encoding = 'utf-8'
#     # logger.debug('encoded...')
#     # page = page.text
#     # logger.debug('to text...')
#     return page

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


# ------- JSON FILE FUNCTIONS -------
#------------------------------------

# OPEN JSON FILE 
async def open_json(path):
    with open(path,"r") as f:
        return json.load(f)

# WRITE JSON FILE
async def write_json(path, data):
    with open(path,"w") as f:
        json.dump(data, f, indent=4)


# ------- DATABASE FUNCTIONS --------
#------------------------------------

# BOT ADDED TO NEW SERVER, POPULATE DATABASES
async def add_server_db(serv_id, serv_name):
    # update servers_path DB
    rel_serv = {
        serv_id: {
            'serv_name': serv_name,
            'chan_id': None,
            'rs_role_id': None
        }
    }
    try:
        # load existing json file
        data_s = await open_json(servers_path)
        # append server to json file
        data_s.update(rel_serv)
        # write updated json file
        await write_json(servers_path,data_s)
        new_file_s = False
    except:
        # no json file found
        await write_json(servers_path,rel_serv)
        new_file_s = True

    # update players_path DB
    rel_play = {}
    try:
        # load existing json file
        await open_json(players_path)
        # # append server to json file
        # data_p.update(rel_play)
        # # write updated json file
        # await write_json(players_path,data_p)
        new_file_p = False
    except:
        # no json file found
        await write_json(players_path,rel_play)
        new_file_p = True
    # log results
    if new_file_s == True:
        logger.info(f'\nCreated json file: {servers_path}')
    if new_file_p == True:
        logger.info(f'\nCreated json file: {players_path}')
    logger.info(f'\nNew guild added to databases: {serv_name} | {serv_id}')


# BOT REMOVED FROM SERVER, REMOVE FROM DATABASES
async def del_server_db(serv_id, serv_name):
    data_s = await open_json(servers_path)
    # data_p = await open_json(players_path)
    # delete server in servers DB
    if str(serv_id) in data_s:
        del data_s[str(serv_id)]
    # # delete server in players DB
    # if str(serv_id) in data_p:
    #     del data_p[str(serv_id)]
    await write_json(servers_path,data_s)
    # await write_json(players_path,data_p)
    logger.info(f'\nGuild removed from databases: {serv_name} | {serv_id}')


### NEW PLAYERPATH METHODS ###

# CHECK IF PLAYER ID IS IN DB
async def player_exists_in_db(player_id):
    data = await open_json(players_path)
    for a in data.keys():
        if a == str(player_id):
            return True
    return False


# CHECK IF SERVER ID IS IN PLAYER
async def server_exists_in_player(player_id, server_id):
    data = await open_json(players_path)
    for a in data.keys():
        if a == str(player_id):
            if str(server_id) in data[a]['servers']:
                return True
    return False


# RETURN PLAYER AS DICT FROM DB
async def get_player_entry(player_id):
    data = await open_json(players_path)
    for a in data.keys():
        if a == str(player_id):
            return data[a]


# RETURN ONE VALUE FROM PLAYER
async def get_player_val(player_id, key):
    data = await open_json(players_path)
    for a in data.keys():
        if a == str(player_id):
            player = data[a]
            return player[key]


# UPDATE ENTIRE PLAYER ENTRY
async def update_player_entry(player_id, new_entry):
    data = await open_json(players_path)
    data[str(player_id)] = new_entry
    await write_json(players_path, data)


# UPDATE ONE VALUE FOR A PLAYER
async def update_player_val(player_id, key, new_val):
    data = await open_json(players_path)
    player = data[str(player_id)]
    player[key] = new_val
    data[str(player_id)] = player
    await write_json(players_path, data)


# DELETE A PLAYER ENTRY IN PLAYER PATH
async def del_player_entry(player_id):
    data = await open_json(players_path)
    if str(player_id) in data:
        del data[str(player_id)]
        await write_json(players_path, data)
        return True
    else:
        return False


### LEGACY METHODS WHEN SERVERS WERE KEYS IN PLAYERPATH ###

# RETURN SERVER AS DICT FROM DB
async def get_server_entry(path, serv_id):
    data = await open_json(path)
    for a in data.keys():
        if a == str(serv_id):
            return data[a]


# RETURN ONE VALUE FROM SERVER
async def get_server_val(path, serv_id, key):
    data = await open_json(path)
    for a in data.keys():
        if a == str(serv_id):
            server = data[a]
            return server[key]


# UPDATE ONE VALUE FOR A SERVER
async def update_server_val(path, serv_id, key, new_val):
    data = await open_json(path)
    server = data[str(serv_id)]
    server[key] = new_val
    data[str(serv_id)] = server
    await write_json(path, data)


# DELETE A KEY FROM A SERVER
async def del_server_key(path, serv_id, key):
    data = await open_json(path)
    server = data[str(serv_id)]
    if str(key) in server:
        del server[str(key)]
        data[str(serv_id)] = server
        await write_json(path,data)
        return True
    else:
        return False

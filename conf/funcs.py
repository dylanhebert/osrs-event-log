import discord
from discord.ext import commands
import time
import asyncio
import aiohttp
import json
from conf.logger import logger
import requests
from bs4 import BeautifulSoup

# --- VARIABLES ---
# paths to json files
serversPath = '/home/pi/code_pi/osrseventlog/data/rel_servers.json'
playersPath = '/home/pi/code_pi/osrseventlog/data/rel_players.json'

# HISCORES PAGE (before username)
hiscoresURL = "https://secure.runescape.com/m=hiscore_oldschool/hiscorepersonal?user1="

# ------- NON-ASYNC FUNCTIONS -------
#------------------------------------

# FORMAT NAME: DISCORD -> RS
def NameToRS(name):
    if ' ' in name:
        name = name.replace(' ', '+')
        return name.title()
    else:
        return name.title()

# FORMAT NAME: RS -> DISCORD
def NameToDiscord(name):
    if '+' in name:
        name = name.title().replace('+', ' ')
        return name
    else:
        name = name.title()
        return name

# MINUTES CONVERTER
async def timeMins(secs):
    minutes = secs * 60
    return minutes

# COMPARE OLD VS NEW XP
def xpChanged(old, new):
    if old != new:
        return True
    else:
        return False

# FORMAT COMMAS IN LONG INTS
def formatInt(num):
    if "," in num:
        num = int(num.replace(",", ""))
    else:
        num = int(num)
    return num

# FORMAT COMMAS IN LONG INTS #2
def formatIntStr(num):
    if len(str(num)) >= 4:
        num = "{:,}".format(num)
    else:
        num = str(num)
    return num


# ------ BASIC ASYNC FUNCTIONS ------
#------------------------------------

# CHECK IF A MEMBER IS ADMIN
async def isAdmin(mem):
    if mem.guild_permissions.administrator == True:
        return True
    else:
        return False

# CHECK IF A RS PLAYER IS ACCEPTABLE
async def PlayerIsAcceptable(name):
    page = await getPage(hiscoresURL, name)
    if page != None:
        try:
            logger.info(f"{name} has a valid hiscores page!")
            playerDict = await getPlayerScores(name, page)
            return playerDict
        except Exception as e:
            logger.exception(f'Unable to parse player hiscores: {name} | {e}')
            return None
    else:
        logger.info(f'Unable to get player: {name} | Page status: None')
        return None


# ------- WEB FUNCTIONS -------
#------------------------------

# REQUEST WEB PAGE (AIOHTTP)
async def getPage(url, name):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url + name) as p:
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


# REQUEST WEB PAGE (REQUESTS) (OLD)
async def getPageRequests(url, name):
    try:
        page = requests.get(url + name)
    except:
        page = None
        logger.debug('requests.get failed! Returning None')
    logger.debug('scraped...')
    # page.encoding = 'utf-8'
    # logger.debug('encoded...')
    # page = page.text
    # logger.debug('to text...')
    return page

# GET A PLAYERS SCORES INTO DICT
async def getPlayerScores(nameRS, page):
    parseMinigames = False
    logger.debug(f'{nameRS}: got page...')
    soup = BeautifulSoup( page, 'html.parser' )
    logger.debug(f'{nameRS}: got soup...')
    scores = soup.find(id="contentHiscores")
    logger.debug(f'{nameRS}: got scores...')
    # new player dict to fill and return to correct discord id
    playerDict = {
        'rsName' : nameRS,
        'servers' : {},
        'skills' : {},
        'minigames': {}
    }
    # check if player has no hiscore profile
    logger.debug(f'{nameRS}: contents[1]: '+scores.contents[1].name)
    if scores.contents[1].name != 'table':  # if there's no table, the player has no scores
        logger.info(f"{rsdata['rsName']} not found! Appended empty playerDict.")
        return playerDict
    # player has hiscore profile
    logger.debug(f"{nameRS}: found player...")
    for tr in scores.find_all('tr')[3:]:
        if 'Minigame' in tr.get_text():
            parseMinigames = True
            continue
        rowEntry = tr.find_all('td')
        skill = rowEntry[1].get_text().strip()
        skillDict = {}
        skillDict['rank'] = rowEntry[2].get_text()
        if not parseMinigames:
            skillDict['level'] = rowEntry[3].get_text()
            skillDict['xp'] = rowEntry[4].get_text()
            playerDict['skills'][skill] = skillDict  # update skill to skills dict
        else:
            skillDict['score'] = rowEntry[3].get_text()
            playerDict['minigames'][skill] = skillDict  # update clue/boss to minigames dict
    logger.info(f"{nameRS}: Successfully created dict for {nameRS}!")
    return playerDict


# ------- JSON FILE FUNCTIONS -------
#------------------------------------

# OPEN JSON FILE 
async def openJson(path):
    with open(path,"r") as f:
        return json.load(f)

# WRITE JSON FILE
async def writeJson(path,data):
    with open(path,"w") as f:
        json.dump(data, f, indent=4)


# ------- DATABASE FUNCTIONS --------
#------------------------------------

# BOT ADDED TO NEW SERVER, POPULATE DATABASES
async def addServerDB(servID,servName):
    # update serversPath DB
    relServ = {
        servID: {
            'servName': servName,
            'chanID': None,
            'rsRoleID': None
        }
    }
    try:
        # load existing json file
        dataS = await openJson(serversPath)
        # append server to json file
        dataS.update(relServ)
        # write updated json file
        await writeJson(serversPath,dataS)
        newFileS = False
    except:
        # no json file found
        await writeJson(serversPath,relServ)
        newFileS = True

    # update playersPath DB
    relPlay = {}
    try:
        # load existing json file
        dataP = await openJson(playersPath)
        # # append server to json file
        # dataP.update(relPlay)
        # # write updated json file
        # await writeJson(playersPath,dataP)
        newFileP = False
    except:
        # no json file found
        await writeJson(playersPath,relPlay)
        newFileP = True
    # log results
    if newFileS == True:
        logger.info(f'\nCreated json file: {serversPath}')
    if newFileP == True:
        logger.info(f'\nCreated json file: {playersPath}')
    logger.info(f'\nNew guild added to databases: {servName} | {servID}')


# BOT REMOVED FROM SERVER, REMOVE FROM DATABASES
async def delServerDB(servID,servName):
    dataS = await openJson(serversPath)
    # dataP = await openJson(playersPath)
    # delete server in servers DB
    if str(servID) in dataS:
        del dataS[str(servID)]
    # # delete server in players DB
    # if str(servID) in dataP:
    #     del dataP[str(servID)]
    await writeJson(serversPath,dataS)
    # await writeJson(playersPath,dataP)
    logger.info(f'\nGuild removed from databases: {servName} | {servID}')


### NEW PLAYERPATH METHODS ###

# CHECK IF PLAYER ID IS IN DB
async def playerExistsInDB(playerID):
    data = await openJson(playersPath)
    for a in data.keys():
        if a == str(playerID):
            return True
    return False


# CHECK IF SERVER ID IS IN PLAYER
async def serverExistsInPlayer(playerID,serverID):
    data = await openJson(playersPath)
    for a in data.keys():
        if a == str(playerID):
            if str(serverID) in data[a]['servers']:
                return True
    return False


# RETURN PLAYER AS DICT FROM DB
async def getPlayerEntry(playerID):
    data = await openJson(playersPath)
    for a in data.keys():
        if a == str(playerID):
            return data[a]


# RETURN ONE VALUE FROM PLAYER
async def getPlayerVal(playerID,key):
    data = await openJson(playersPath)
    for a in data.keys():
        if a == str(playerID):
            player = data[a]
            return player[key]


# UPDATE ENTIRE PLAYER ENTRY
async def updatePlayerEntry(playerID,newEntry):
    data = await openJson(playersPath)
    data[str(playerID)] = newEntry
    await writeJson(playersPath,data)


# UPDATE ONE VALUE FOR A PLAYER
async def updatePlayerVal(playerID,key,newVal):
    data = await openJson(playersPath)
    player = data[str(playerID)]
    player[key] = newVal
    data[str(playerID)] = player
    await writeJson(playersPath,data)


# DELETE A PLAYER ENTRY IN PLAYER PATH
async def delPlayerEntry(playerID):
    data = await openJson(playersPath)
    if str(playerID) in data:
        del data[str(playerID)]
        await writeJson(playersPath,data)
        return True
    else:
        return False


### LEGACY METHODS WHEN SERVERS WERE KEYS IN PLAYERPATH ###

# RETURN SERVER AS DICT FROM DB
async def getServerEntry(path,servID):
    data = await openJson(path)
    for a in data.keys():
        if a == str(servID):
            return data[a]


# RETURN ONE VALUE FROM SERVER
async def getServerVal(path,servID,key):
    data = await openJson(path)
    for a in data.keys():
        if a == str(servID):
            server = data[a]
            return server[key]


# UPDATE ONE VALUE FOR A SERVER
async def updateServerVal(path,servID,key,newVal):
    data = await openJson(path)
    server = data[str(servID)]
    server[key] = newVal
    data[str(servID)] = server
    await writeJson(path,data)


# DELETE A KEY FROM A SERVER
async def delServerKey(path,servID,key):
    data = await openJson(path)
    server = data[str(servID)]
    if str(key) in server:
        del server[str(key)]
        data[str(servID)] = server
        await writeJson(path,data)
        return True
    else:
        return False

# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer — see general.py. Every message string here is byte-for-byte
# what it was before the migration; only the data access changed.

import datetime
import random

from common.logger import logger
import common.util as util
from data import repo
from . import helpers as h

# --------------------------------- CONSTANTS -------------------------------- #

SOTW_PATH = h.FULL_DATA_PATH + "sotw/"
SOTW_POOL = SOTW_PATH + "all_skills.json"          # tracked in git, still a file

# The store has to be open before the config can be read. ensure_db() is
# idempotent, and this mirrors the old behaviour of reading sotw_config.json at
# import time. osrs-event-log.py also calls verify_files() at startup.
# Import must not create the database — see helpers.open_db_if_exists(). If it
# is not there yet, start with an empty config; handlers.verify_files() opens
# the real one at startup and reloads this.
SOTW_CONFIG = repo.competitions.get_config('sotw') if h.open_db_if_exists() else {}
logger.debug('Loaded SOTW config into cache.')


def reload_config():
    """Re-read the config from whichever database is currently open.

    SOTW_CONFIG is populated at import time, which binds it to whatever
    ensure_db() opened first. That is correct for the bot — cwd is fixed and the
    database is already migrated — but not for anything that connects to a
    different database afterwards, such as a test using a scratch copy. Those
    would otherwise keep an empty dict and fail with KeyError: 'current_skill'
    deep inside message building.
    """
    global SOTW_CONFIG
    SOTW_CONFIG = repo.competitions.get_config('sotw')
    return SOTW_CONFIG

SOTW_BASIC_FMT = "%m-%d-%y"         # String format for basic SOTW displaying and saving
SOTW_COMPARE_FMT = "%m-%d-%y %H"    # String format for comparing times
PRE_PICK_HOURS = 1                  # Hours before pick time to show hiscores once more
TOP_PLAYERS_COUNT = 10              # Number of players to show on SOTW info and get SOTW histories
DAYS_BETWEEN_SOTW = 7               # SHOULD BE 7, Days to the next SOTW reset

RANK_AWARDS = {
    1: 'Rune Trophy',
    2: 'Adamant Trophy',
    3: 'Mithril Trophy'
}

MESSAGE_DIVIDER = "\n~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n"


# --------------------- Get top SOTW players in a server --------------------- #

async def get_sotw_top_players(server_id):
    """Players with xp > 0, highest first, capped at TOP_PLAYERS_COUNT."""
    return repo.competitions.top_players(server_id, 'sotw', TOP_PLAYERS_COUNT)


# --------------------- Reset every player's XP for SOTW --------------------- #

async def reset_sotw_xp():
    repo.competitions.reset_scores('sotw')


# ----------------------- Build ranks from top players ----------------------- #

async def ranks_from_top_players(top_players, join_to_str=True, give_awards=False):
    try:
        ranks_list = []
        i = 1
        for player in top_players:
            if give_awards and i <= 3: award = f'  - **{RANK_AWARDS[i]}**'
            else: award = ''
            ranks_list.append(f"{i}: **{util.name_to_discord(player['player'])}** - {util.format_int_str(player['xp'])} XP{award}")
            i += 1
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    if join_to_str:
        ranks_list = '\n'.join(ranks_list)
    return ranks_list

# Build the Final String for ranks
async def build_final_rank_str(ranks_list, skill, old_date=None):
    if old_date:
        # Bring in an old date, may be checking history
        deadline = datetime.datetime.strptime(old_date, SOTW_BASIC_FMT)
        return f"Skill of the Week: **{skill}**  |  **Final Rankings**  |  *{deadline.strftime('%A, %B %d, %Y')}*\n" + ranks_list
    else:
        # Progress report or command called
        deadline = datetime.datetime.strptime(f"{SOTW_CONFIG['pick_next']} {SOTW_CONFIG['pick_hour']}", SOTW_COMPARE_FMT)
        return f"Skill of the Week: **{skill}**  |  Deadline: **{deadline.strftime('%A, %B %d at %-I%p')} CST**\n" + ranks_list


# Build the Final String for stats
async def build_final_stats_str(sort_players):
    try:
        ranks_list = [f"Skill of the Week: **Player Trophies**"]
        for player in sort_players:
            player_str = f"**{player['name']}** - Score Total: **{player['rank_weight']}**"
            if player['rank_1'] > 0:
                player_str = player_str + f" | Rune: **{player['rank_1']}**"
            if player['rank_2'] > 0:
                player_str = player_str + f" | Adamant: **{player['rank_2']}**"
            if player['rank_3'] > 0:
                player_str = player_str + f" | Mithril: **{player['rank_3']}**"
            ranks_list.append(player_str)
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    return ranks_list


# ------------------------- Get SOTW Info for Server ------------------------- #

async def get_sotw_info(Server, pre_time=False):
    """Get all basic SOTW info for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET SOTW INFO - Server: {Server.name} | ID: {Server.id}')
    top_players = await get_sotw_top_players(Server.id)
    ranks_list = await ranks_from_top_players(top_players)
    final_str = await build_final_rank_str(ranks_list, skill=SOTW_CONFIG['current_skill'])
    if pre_time:
        final_str = "**LAST CHANCE!** This Skill of the Week is almost over!" + MESSAGE_DIVIDER + final_str
    logger.info(f"FINISHED GET SOTW INFO - Server: {Server.name} | ID: {Server.id}")
    return final_str


async def get_sotw_history(Server):
    """Get all basic SOTW history for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET SOTW HISTORY - Server: {Server.name} | ID: {Server.id}')
    history_list = []
    for week in repo.competitions.history(Server.id, 'sotw'):
        ranks_list = await ranks_from_top_players(week['players'], give_awards=True)
        history_list.append(await build_final_rank_str(ranks_list, skill=week['skill'], old_date=week['date']))
    logger.info(f"FINISHED GET SOTW HISTORY - Server: {Server.name} | ID: {Server.id}")
    return history_list


async def get_sotw_stats(Server):
    """Get all basic SOTW player stats for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET SOTW STATS - Server: {Server.name} | ID: {Server.id}')
    # One grouped query instead of rebuilding every week in Python on each call.
    sort_players = repo.competitions.standings(Server.id, 'sotw')
    final_players = await build_final_stats_str(sort_players)
    logger.info(f"FINISHED GET SOTW STATS - Server: {Server.name} | ID: {Server.id}")
    return final_players


# ----------------------------- Check SOTW Times ----------------------------- #

async def check_sotw_times(now_time):
    """Checks the datetime.now with the time in SOTW config"""
    logger.debug('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.debug(f'Initialized CHECK SOTW TIMES - Time Now: {now_time}')
    # fix for somparing strings with single digit ints
    if len(str(SOTW_CONFIG['pick_hour'])) == 1:
        pick_hour = f"0{SOTW_CONFIG['pick_hour']}"
    else:
        pick_hour = str(SOTW_CONFIG['pick_hour'])
    # If it's time to pick new SOTW
    pick_time_str = f"{SOTW_CONFIG['pick_next']} {pick_hour}"
    pick_time_dt = datetime.datetime.strptime(pick_time_str, SOTW_COMPARE_FMT)
    if now_time >= pick_time_dt:
        SOTW_CONFIG['pick_imminent'] = False
        logger.info('Pick Time! Reset pick_imminent.')
        return 'pick_time'
    # Remind for 1 hour left
    if not SOTW_CONFIG['pick_imminent']:
        pick_imm_str = f"{SOTW_CONFIG['pick_next']} {int(pick_hour) - PRE_PICK_HOURS}"
        pick_imm_dt = datetime.datetime.strptime(pick_imm_str, SOTW_COMPARE_FMT)
        if now_time >= pick_imm_dt:
            SOTW_CONFIG['pick_imminent'] = True
            await update_sotw_config(SOTW_CONFIG)
            logger.info('Pre Time! Enabled pick_imminent')
            return 'pre_time'
    # If it's time to post progress
    for post_hour in SOTW_CONFIG['progress_hours']:
        if not post_hour['done']:
            if now_time.hour == post_hour['hour']:
                post_hour['done'] = True
                await update_sotw_config(SOTW_CONFIG)
                logger.info(f"Progress time! Hour: {post_hour['hour']}")
                return 'progress_time'
        else:
            if now_time.hour != post_hour['hour']:
                post_hour['done'] = False
                await update_sotw_config(SOTW_CONFIG)
                logger.info(f"Reset Done parameter for hour: {post_hour['hour']}")
    logger.debug(f'No time matches!')
    return None


# -------- Build final SOTW strings for servers & update players in DB ------- #

async def build_sotw_final(now_time):
    """Reset all servers for Skill of the week and add final rankings to players"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized SOTW RESET')
    all_servers = []
    all_messages = {}

    # One transaction for every server's history plus the score reset, so a
    # crash cannot leave some servers recorded and others not, with scores
    # already zeroed and no way to recover them.
    with repo.transaction():
        for serv_dict in repo.servers.list_for_competition('sotw'):
            server = serv_dict['id']
            logger.debug(f'In server {server}...')
            all_servers.append(serv_dict)
            top_players = await get_sotw_top_players(server)
            ranks_list = await ranks_from_top_players(top_players, give_awards=True)
            final_str = ("**Congratulations** to the winners!" + MESSAGE_DIVIDER +
                    await build_final_rank_str(ranks_list, skill=SOTW_CONFIG['current_skill'], old_date=now_time.strftime(SOTW_BASIC_FMT))
                    + MESSAGE_DIVIDER)
            logger.debug('Got top players...')

            placements = []
            i = 1
            for pd in top_players[:3]:
                placements.append({'player': pd['player'], 'xp': pd['xp'], 'rank': i})
                i += 1
            repo.competitions.record_week(
                server, 'sotw', SOTW_CONFIG['current_skill'],
                now_time.strftime(SOTW_BASIC_FMT), placements)
            logger.debug('Appended history!')
            all_messages[str(server)] = final_str
            logger.debug('Added final message!')

        await reset_sotw_xp()
        logger.info('Set all SOTW XP to 0!')

    logger.debug('Wrote all to DB!')
    return {
        'all_servers': all_servers,
        'all_messages': all_messages
    }


# --------------------- Change to a new Skill of the Week -------------------- #

async def change_new_sotw(now_time):
    """Change to new SOTW & build a message string with new SOTW"""
    global SOTW_CONFIG
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f"Initialized CHANGE NEW SOTW - Old SOTW: {SOTW_CONFIG['current_skill']}")
    current_skill = SOTW_CONFIG['current_skill']
    skill_pool = await h.db_open(SOTW_POOL)
    new_skill_override = None
    # Re-read so an override written out of band (by hand, or a future admin
    # command) is picked up, the way re-reading sotw_config.json used to allow.
    SOTW_CONFIG_TEMP = repo.competitions.get_config('sotw')
    if SOTW_CONFIG_TEMP.get('pick_override') and SOTW_CONFIG_TEMP['pick_override'] in skill_pool['all_skills']:
        new_skill_override = SOTW_CONFIG_TEMP['pick_override']
        SOTW_CONFIG = SOTW_CONFIG_TEMP
    SOTW_CONFIG['pick_override'] = None
    del SOTW_CONFIG['recent_skills'][0]
    SOTW_CONFIG['recent_skills'].append(current_skill)
    if new_skill_override:
        SOTW_CONFIG['current_skill'] = new_skill_override
    else:
        while current_skill in SOTW_CONFIG['recent_skills']:
            current_skill = random.choice(skill_pool['all_skills'])
        SOTW_CONFIG['current_skill'] = current_skill

    target_weekday = SOTW_CONFIG["pick_weekday"]
    days_ahead = (target_weekday - now_time.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7  # Always get the *next* occurrence
    new_deadline = now_time + datetime.timedelta(days=days_ahead)
    SOTW_CONFIG['pick_next'] = new_deadline.strftime(SOTW_BASIC_FMT)

    await update_sotw_config(SOTW_CONFIG)
    new_sotw_message = f"The new Skill of the Week is **{SOTW_CONFIG['current_skill']}**! The deadline is on *{new_deadline.strftime('%A, %B %d')}*. Get skilling!"
    logger.info(f"FINISHED CHANGE NEW SOTW - New SOTW: {SOTW_CONFIG['current_skill']} | New deadline: {new_deadline.strftime(SOTW_BASIC_FMT)}")
    return new_sotw_message


async def update_sotw_config(config_new):
    """Update the entire SOTW config with current config in cache"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized UPDATE SOTW CONFIG')
    global SOTW_CONFIG
    SOTW_CONFIG = config_new
    repo.competitions.set_config('sotw', SOTW_CONFIG)
    logger.info(f'FINISHED UPDATE SOTW CONFIG')


async def get_sotw_servers(progress):
    """Gets all settings in all servers with sotw enabled"""
    logger.debug('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.debug(f'Initialized GET SOTW SERVERS - Progress report: {progress}')
    all_servers = repo.servers.list_for_competition('sotw', progress_only=bool(progress))
    logger.debug(f"FINISHED GET SOTW SERVERS - Progress report: {progress}")
    return all_servers


async def get_sotw_entry(entry):
    """Gets a single entry from SOTW config"""
    return SOTW_CONFIG[entry]


# NEEDS WORK
async def add_sotw_progress_hour(new_hour):
    """Adds a new sotw progress hour, reorganizes list by hour"""
    pass


# NEEDS WORK
async def remove_sotw_progress_hour(rm_hour):
    """Removes an existing sotw progress hour, sends back exception if hour not there"""
    pass

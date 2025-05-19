# OSRS Activity Log Bot: PlayerUpdate.py
# - PlayerUpdate class that builds messages to be sent into a Discord channel
#

import discord
import asyncio
from common.logger import logger
import common.util as util
import math
import data.handlers as db


# ---------------------------------------------------------------------------- #
#                                   VARIABLES                                  #
# ---------------------------------------------------------------------------- #

custom_messages = db.get_custom_messages()

non_monster_bosses =  [   "Barrows Chests", "Chambers of Xeric", "Theatre of Blood",
                        "Theatre of Blood: Hard Mode", "The Gauntlet", "The Corrupted Gauntlet", "Wintertodt",
                        "Chambers of Xeric: Challenge Mode", "Tempoross",
                        "Guardians of the Rift", "Tombs of Amascut", "Tombs of Amascut: Expert Mode",
                        "LMS - Rank", "PvP Arena - Rank", "Soul Wars Zeal",
                        "Bounty Hunter - Hunter", "Bounty Hunter - Rogue",
                        "Bounty Hunter (Legacy) - Hunter", "Bounty Hunter (Legacy) - Rogue",
                        "Collections Logged"
                    ]

title_replacements = {  "Rifts closed" : "Guardians of the Rift" }

# ---------------------------------------------------------------------------- #
#                                HELPER METHODS                                #
# ---------------------------------------------------------------------------- #

def clue_sort(title):
    if '(all)' in title:
        return 'Total'
    if '(beginner)' in title:
        return 'Beginner'
    if '(easy)' in title:
        return 'Easy'
    if '(medium)' in title:
        return 'Medium'
    if '(hard)' in title:
        return 'Hard'
    if '(elite)' in title:
        return 'Elite'
    if '(master)' in title:
        return 'Master'


# ---------------------------------------------------------------------------- #
#                              PLAYER UPDATE CLASS                             #
# ---------------------------------------------------------------------------- #

class PlayerUpdate:
    def __init__(self, rs_name, old_data, player_discord_info):
        self.old_data = old_data
        self.rs_name = util.name_to_discord(rs_name)
        self.player_discord_info = player_discord_info
        self.mention_member = None
        self.mention_role = None
        self.overall_update = None
        self.skills = []
        self.minigames = []
        self.milestones = []
        self.clue_all_total = None
        self.duplicate_server_post = False  # fix for duplicate 'Overall' entries & logging when a player is in multiple servers
        self.custom_messages = custom_messages
        self.new_sotw_xp = None
        self.new_botw_kills = None


# ------------------------------ Post Update(s) ------------------------------ #

    async def post_update(self, bot, server, channel, rs_role, player_server):
        # gather all server-specific variables we need
        logger.debug(f"rs_name: {self.rs_name}, skill_updates: {len(self.skills)}, minigame_updates: {len(self.minigames)}, milestones: {len(self.milestones)}...")
        self.get_mention_member(server, player_server)  # build our mention string
        self.get_mention_role(rs_role)  # build our mention string

        # MILESTONE UPDATES
        if self.milestones:
            # only add overall info here if there's no regular update
            if self.overall_update != None and not self.skills:
                if self.duplicate_server_post == False:
                    self.milestones.append(self.overall_update)
                    # Append SOTW info if needed
                    self.check_sotw_update('milestones')
                    # Append BOTW info if needed
                    self.check_botw_update('milestones')
                    logger.debug(f"joined overall for milestone...")
            all_milestones = "".join(self.milestones)
            full_message = f'**~ {self.mention_role} {self.mention_member} ~**\n{all_milestones}'
            ### Add in code here later to work around Discord's 2k char limit ###
            await channel.send(full_message)
            if self.duplicate_server_post == False:
                logger.info(f"New milestone posted for {self.rs_name} | Milestones posted: {len(self.milestones)}:\n{full_message}")

        # REGULAR UPDATES
        all_skills = ""
        all_minigames = ""
        # skill updates
        if self.skills:
            # Append SOTW info if needed
            # add overall info to bottom of skills in update
            if self.overall_update != None:
                if self.duplicate_server_post == False:
                    self.skills.append(self.overall_update)
                    self.check_sotw_update('skills')
                    logger.debug(f"joined overall...")
                else:
                    logger.debug(f"overall already joined, not appending...")
            all_skills = "".join(self.skills)
            logger.debug(f"created all_skills...")
        # minigame updates
        if self.minigames:
            # Append BOTW info if needed
            self.check_botw_update('bosses')
            all_minigames = "".join(self.minigames)
            logger.debug(f"created all_minigames...")
        # post updates
        if all_skills or all_minigames:
            full_message = f'**~ {self.mention_member} ~**\n{all_skills}{all_minigames}'
            ### Add in code here later to work around Discord's 2k char limit ###
            await channel.send(full_message)
            if self.duplicate_server_post == False:
                logger.info(f"New update posted for {self.rs_name} | Updates posted: {len(self.skills) + len(self.minigames)}:\n{full_message}")
        
        # We've now posted to our first server, others will be duplicates
        self.duplicate_server_post = True
        return


    # Mention Member in Server?
    def get_mention_member(self, server, player_server):
        member = server.get_member(player_server['member'])
        if player_server['mention'] == True:
            self.mention_member = member.mention  # CHANGE FOR TESTING
        else:
            self.mention_member = member.name

    # --- BUILD ROLE MENTION STRING --- #
    # defaults to @here when no role specified
    def get_mention_role(self, rs_role):
        if rs_role == None:
            self.mention_role = "@here"
        else:
            self.mention_role = rs_role.mention

    # --- CHECK FOR UPDATES --- #
    def has_any_updates(self):
        if self.skills or self.minigames or self.milestones:
            return True
        else:
            return False
        
    # --- CHECK FOR SOTW APPEND --- #
    def check_sotw_update(self, list_append):
        if self.new_sotw_xp:
            sotw_str = f'```c\nSkill of the Week - Current {db.SOTW_CONFIG["current_skill"]} XP: {util.format_int_str(self.new_sotw_xp)}```'
            if list_append == 'skills':
                self.skills.append(sotw_str)
                return
            if list_append == 'milestones':
                self.milestones.append(sotw_str)
                return

    # --- GET CORRECT WORD FOR BOSS KILLS --- #
    def get_boss_terms(self, boss_name):
        # check title replacements first
        if boss_name in title_replacements:
            boss_name = title_replacements[boss_name]
        # change first word depending on boss/activity
        boss_terms = [ 'killed', 'kill' ]  # any other boss will default to this
        if boss_name in non_monster_bosses:  # not monsters
            if boss_name == "Wintertodt" or boss_name == "Tempoross":  # special case for skilling bosses
                boss_terms = [ 'subdued', 'subdue' ]
                logger.debug("nonmonster boss, skilling boss...")
            elif boss_name == "Collections Logged":
                boss_terms = [ 'progressed', 'collection' ]
                logger.debug("nonmonster boss, collections logged...")
            else:  # anything else not skilling bosses
                boss_terms = [ 'completed', 'completion' ]
                logger.debug("nonmonster boss...")
        return boss_terms

    # --- CHECK FOR BOTW APPEND --- #
    def check_botw_update(self, list_append):
        if self.new_botw_kills:
            boss_terms = self.get_boss_terms(db.BOTW_CONFIG["current_boss"])
            botw_str = f'```c\nBoss of the Week - Current {db.BOTW_CONFIG["current_boss"]} {boss_terms[1]}s: {util.format_int_str(self.new_botw_kills)}```'
            if list_append == 'bosses':
                self.minigames.append(botw_str)
                return
            if list_append == 'milestones':
                self.milestones.append(botw_str)
                return


# ---------------------------------------------------------------------------- #
#                            UPDATE CREATION METHODS                           #
# ---------------------------------------------------------------------------- #

# ---------------------------------- SKILLS ---------------------------------- #

    async def update_skill(self, new_data, title, new_entry):
        logger.debug("in PlayerUpdate-update_skill...")

        # skill was already on hiscores
        if not new_entry:  
            old_data = self.old_data['skills'][title]
            logger.debug(f"existing entry, old lvl: {old_data['level']}, new lvl: {new_data['level']}...")
            xp_new = util.format_int(new_data['xp'])
            xp_old = util.format_int(old_data['xp'])
            xp_diff = xp_new - xp_old
            logger.debug("calculated xp diff...")
            if new_data['level'] != old_data['level']:  # check if level change
                logger.debug("difference in level...")
                # only add new Overall info below any skills updates
                if title == 'Overall':
                    self.make_overall_update(old_data, new_data)  # send to make method
                # updating skill that already exists on hiscores
                else: self.make_skill_update(old_data, new_data, title, xp_diff)
            else:  # xp gain, but no level change
                logger.debug(f"{title} had no lvl change, xp diff: {xp_diff}...")

            # check for any significant XP updates
            if xp_new >= 10000000:
                self.check_xp_update(old_data, new_data, title, xp_new, xp_old, xp_diff)
                           
            # Check if skill is SOTW, add xp to current SOTW xp
            if title == db.SOTW_CONFIG['current_skill']:
                self.new_sotw_xp = await db.add_to_player_entry_global(util.name_to_rs(self.rs_name), 'sotw_xp', xp_diff)

        # skill is new to hiscores
        else:
            logger.debug("new entry...")
            message = f"**{self.rs_name} levelled up {title} to {new_data['level']}**\
                        ```This is the first time this skill is on the Hiscores```"
            self.skills.append(message)
            logger.debug(f"appended NEW update for {title} to skills list...")


# --------------------------------- MINIGAMES -------------------------------- #

    async def update_minigame(self, new_data, title, new_entry):
        logger.debug("in PlayerUpdate-update_minigame...")

        # CLUES
        if 'Clue' in title:
            logger.debug("found clue...")
            clue_lvl = clue_sort(title)
            logger.debug(f"clue lvl: {clue_lvl}...")

            if not new_entry:  # minigame was already on hiscores
                logger.debug("existing entry...")
                old_data = self.old_data['minigames'][title]
                count_new = util.format_int(new_data['score'])
                count_old = util.format_int(old_data['score'])
                count_diff = count_new - count_old
                self.make_clue_update(old_data, new_data, title, count_new, count_old, count_diff, clue_lvl)

            else:  # minigame is new to hiscores
                logger.debug("new entry...")
                # all clue scrolls, get count
                if clue_lvl == 'Total':
                    logger.debug(f"(all) clue found, count: {new_data['score']}...")
                    self.clue_all_total = util.format_int(new_data['score'])
                    return
                # set correct usage of a/an
                if clue_lvl in ['Easy', 'Elite']: an = 'an'
                else: an = 'a'
                # append total clues to message if total clues rank is on hiscores
                if self.clue_all_total != None:
                    total_clue_msg = f" | Total clues completed: {util.format_int_str(self.clue_all_total)}"
                else:
                    total_clue_msg = ""
                message = f"**{self.rs_name} completed {an} {clue_lvl} Clue Scroll for the first time**\
                            ```c\n{clue_lvl} clues completed: {util.format_int_str(new_data['score'])} | Current rank: {new_data['rank']}{total_clue_msg}```"
                self.minigames.append(message)
                logger.debug(f"appended update for {title} to minigames list...")

        # BOUNTY HUNTER
        elif 'Bounty Hunter' in title:
            # do BH sorting stuff
            return

        # BOSS
        else:
            logger.debug("found boss...")
            boss_terms = self.get_boss_terms(title)

            if not new_entry:  # minigame was already on hiscores
                logger.debug("existing entry...")
                old_data = self.old_data['minigames'][title]
                kill_new = util.format_int(new_data['score'])
                kill_old = util.format_int(old_data['score'])
                kill_diff = kill_new - kill_old
                self.make_boss_update(old_data, new_data, title, kill_new, kill_old, kill_diff, boss_terms[0], boss_terms[1])

                # Check if boss is BOTW, add xp to current BOTW xp
                if title == db.BOTW_CONFIG['current_boss']:
                    self.new_botw_kills = await db.add_to_player_entry_global(util.name_to_rs(self.rs_name), 'botw_kills', kill_diff)

            else:  # minigame is new to hiscores
                logger.debug("new entry...")
                # check if this was a special boss
                if title in self.custom_messages['bosses']:
                    message_extra = self.custom_messages['bosses'][title]
                    message = f"**{self.rs_name} {boss_terms[0]} {title} enough times to be on the hiscores! {message_extra}**\
                                ```c\nTotal {boss_terms[1]} count: {util.format_int_str(new_data['score'])} | Current rank: {new_data['rank']}```"
                    self.milestones.append(message)
                    logger.debug(f"appended Boss update for {title} to milestones list...")
                else:
                    message = f"**{self.rs_name} {boss_terms[0]} {title} enough times to be on the hiscores!**\
                                ```c\nTotal {boss_terms[1]} count: {util.format_int_str(new_data['score'])} | Current rank: {new_data['rank']}```"
                    self.minigames.append(message)
                    logger.debug(f"appended update for {title} to minigames list...")
            

# ---------------------------------------------------------------------------- #
#                     MESSAGE & MILESTONE CHECKING METHODS                     #
# ---------------------------------------------------------------------------- #

# ---------------------------------- OVERALL --------------------------------- #

    def make_overall_update(self, old_data, new_data):
        logger.debug("assigning Overall...")
        lvl_new = util.format_int(new_data['level'])
        lvl_old = util.format_int(old_data['level'])
        # MAX
        max_lvl = 2277
        if lvl_new == max_lvl and lvl_old != max_lvl:  #  TOTAL LEVEL {new_data['level']}
            message = f"**{self.rs_name} HAS MAXED!!** \U0001F44F \U0001F44F \U0001F44F \U0001F525 \U0001F602 \U0001F44C \U0001F4AF \U0001F44F \U0001F44F \U0001F44F \n*Now you can finally play the game.*\
                        ```c\nOverall XP: {new_data['xp']} | Overall rank: {new_data['rank']}```"
            self.milestones.append(message)
        # 2200 total
        elif lvl_old < 2200 and lvl_new >= 2200:
            message = f"**{self.rs_name} has achieved 2,200 total level**\
                        ```c\nTotal level: {new_data['level']} | Overall XP: {new_data['xp']}```"
            self.milestones.append(message)
        # 2000 total
        elif lvl_old < 2000 and lvl_new >= 2000:
            message = f"**{self.rs_name} has achieved 2,000 total level**\
                        ```c\nTotal level: {new_data['level']} | Overall XP: {new_data['xp']}```"
            self.milestones.append(message)
        # no milestones
        else: self.overall_update = f"```c\nTotal level: {new_data['level']} | Total Overall XP: {new_data['xp']}```"


# ----------------------------------- SKILL ---------------------------------- #

    def make_skill_update(self, old_data, new_data, title, xp_diff):
        logger.debug(f"assigning {title}...")
        new_lvl = new_data['level']
        # special messages for 99
        if new_lvl == '99':
            message_extra = f". {self.custom_messages['max_levels'][title]}"
        # check for special messages
        elif new_lvl in self.custom_messages['levels']:
            message_extra = f". {self.custom_messages['levels'][new_lvl]}"
        else: message_extra = ''
        # make message
        message = f"**{self.rs_name} levelled up {title} to {new_lvl}{message_extra}**\
                    ```c\n{util.format_int_str(xp_diff)} XP gained | Total {title} XP: {new_data['xp']}```"
        # 99 milestone
        if new_lvl == '99':
            self.milestones.append(message)
            logger.debug(f"appended update for {title} to milestones list...")
        # any other level
        else:
            self.skills.append(message)
            logger.debug(f"appended update for {title} to skills list...")

    
# --------------------------------- XP UPDATE -------------------------------- #

    def check_xp_update(self, old_data, new_data, title, xp_new, xp_old, xp_diff):
        logger.debug(f"checking for xp milestones...")
        # check for overall or skill
        if title == 'Overall':
            threshold = 100000000  # 100 million
        else:
            threshold = 10000000  # 10 million
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while xp_new >= threshold:
            if xp_old < threshold:
                message = f"**{self.rs_name} has achieved {util.format_int_str(threshold)} {title} XP**\
                            ```c\n{util.format_int_str(xp_diff)} XP gained | Total {title} XP: {new_data['xp']}```"
                # 10M xp is too low for milestone notification - 2/23/20
                if threshold == 10000000:
                    self.skills.append(message)
                    logger.debug(f"appended XP update for {title} to skills list...")
                else:
                    self.milestones.append(message)
                    logger.debug(f"appended XP update for {title} to milestones list...")
                break
            else:
                threshold += increment
        logger.debug(f"done checking XP...")


# -------------------------------- CLUE UPDATE ------------------------------- #

    def make_clue_update(self, old_data, new_data, title, count_new, count_old, count_diff, clue_lvl):
        # check for clue milestones
        found_milestone = False
        if clue_lvl == 'Total':
            self.clue_all_total = util.format_int(new_data['score'])
            threshold = 250
        else:
            threshold = 100
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while count_new >= threshold:
            if count_old < threshold:
                if clue_lvl != 'Total':  # show total if not already looking at total clues
                    message_extra = f" | Total clues completed: {util.format_int_str(self.clue_all_total)}"
                else: message_extra = ""
                message = f"**{self.rs_name} has completed at least {util.format_int_str(threshold)} {clue_lvl} Clue Scrolls**\
                            ```c\n{clue_lvl} clues completed: {new_data['score']} | Current rank: {new_data['rank']}{message_extra}```"
                self.milestones.append(message)
                logger.debug(f"appended Clue update for {title} to milestones list...")
                found_milestone = True
                break
            else:
                threshold += increment
        # done with loop, check if posting regular update
        if not found_milestone and clue_lvl != 'Total':
            # set correct usage of plural (deprecated)
            # if count_diff == 1: s = ''
            # else: s = 's'
            logger.debug("found diff...")

            # append total clues to message if total clues rank is on hiscores
            if self.clue_all_total != None:
                total_clue_msg = f" | Total clues completed: {util.format_int_str(self.clue_all_total)}"
            else:
                total_clue_msg = ""
            message = f"**{self.rs_name} has completed {new_data['score']} {clue_lvl} Clue Scrolls**\
                        ```c\nNew {clue_lvl} clues logged: {count_diff} | Current rank: {new_data['rank']}{total_clue_msg}```"

            self.minigames.append(message)
            logger.debug(f"appended update for {title} to minigames list...")
        logger.debug(f"done checking Clues...")


# -------------------------------- BOSS UPDATE ------------------------------- #

    def make_boss_update(self, old_data, new_data, title, kill_new, kill_old, kill_diff, action_1, action_2):
        logger.debug(f"assigning Boss: {title}...")
        # check title replacements first
        if title in title_replacements:
            title = title_replacements[title]
            logger.debug(f"changed Boss title: {title}")
        # check for boss milestones
        found_milestone = False
        threshold = 500
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while kill_new >= threshold:
            if kill_old < threshold:
                message = f"**{self.rs_name} has {action_1} {title} at least {util.format_int_str(threshold)} times**\
                            ```c\nTotal {action_2} count: {new_data['score']} | Current rank: {new_data['rank']}```"
                self.milestones.append(message)
                logger.debug(f"appended Boss update for {title} to milestones list...")
                found_milestone = True
                break
            else:
                threshold += increment
        # done with loop, check if posting regular update
        logger.debug("done checking loop...")
        if not found_milestone:
            # set correct tense of time  --not needed anymore, flipped total/new counts - 7/4/20
            # if kill_diff == 1: times = 'time'
            # else: times = 'times'
            logger.debug("found diff...")
            try:
                message = f"**{self.rs_name} has {action_1} {title} {new_data['score']} times**```c\nNew {action_2}s logged: {util.format_int_str(kill_diff)} | Current rank: {new_data['rank']}```"
            except Exception as e:
                logger.exception(f'Error posting boss update: {e}')
            logger.debug("made message...")
            self.minigames.append(message)
            logger.debug(f"appended update for {title} to minigames list...")
        logger.debug(f"done checking Bosses...")



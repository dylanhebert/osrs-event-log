import discord
import asyncio
from conf.logger import logger
import conf.funcs as fs
import math

# -------------- VARIABLES ------------- #
nonMonsterBosses =  [   "Barrows Chests", "Chambers of Xeric", "Theatre of Blood",
                        "The Gauntlet", "The Corrupted Gauntlet", "Wintertodt",
                        "Chambers of Xeric: Challenge Mode"
                    ]

# custom_messages = asyncio.ensure_future(fs.openJson(fs.messagesPath))

# -------------------------------------- #
# ---------- HELPER METHODS ------------ #
# -------------------------------------- #
def clueSort(title):
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


# -------------------------------------------#
# ---------- PLAYER UPDATE CLASS ------------#
# -------------------------------------------#
class PlayerUpdate:
    def __init__(self, oldData, messages):
        self.oldData = oldData
        self.rsName = fs.NameToDiscord(oldData['rsName'])
        self.mentionMember = None
        self.mentionRole = None
        self.overallUpdate = None
        self.skills = []
        self.minigames = []
        self.milestones = []
        self.clueAllTotal = None
        self.duplicateServerPost = False  # fix for duplicate 'Overall' entries & logging when a player is in multiple servers
        self.custom_messages = messages


    # ---------- CLASS METHODS ------------ #

    # --- POST UPDATE(S) --- #
    async def postUpdate(self, bot, server, channel, rsRole, memID):
        # gather all server-specific variables we need
        logger.debug(f"rsName: {self.rsName}, skillUpdates: {len(self.skills)}, minigameUpdates: {len(self.minigames)}, milestones: {len(self.milestones)}...")
        member = server.get_member(memID)
        self.getMentionMember(member,server)  # build our mention string
        self.getMentionRole(rsRole)  # build our mention string

        # MILESTONE UPDATES
        if self.milestones:
            # only add overall info here if there's no regular update
            if self.overallUpdate != None and not self.skills:
                if self.duplicateServerPost == False:
                    self.milestones.append(self.overallUpdate)
                    logger.debug(f"joined overall for milestone...")
            allMilestones = "".join(self.milestones)
            fullMessage = f'**{self.mentionRole} {self.mentionMember} -**\n{allMilestones}'
            ### Add in code here later to work around Discord's 2k char limit ###
            await channel.send(fullMessage)
            if self.duplicateServerPost == False:
                logger.info(f"New milestone posted for {self.rsName} | Milestones posted: {len(self.milestones)}:\n{fullMessage}")

        # REGULAR UPDATES
        allSkills = ""
        allMinigames = ""
        # skill updates
        if self.skills:
            # add overall info to bottom of skills in update
            if self.overallUpdate != None:
                if self.duplicateServerPost == False:
                    self.skills.append(self.overallUpdate)
                    logger.debug(f"joined overall...")
                else:
                    logger.debug(f"overall already joined, not appending...")
            allSkills = "".join(self.skills)
            logger.debug(f"created allSkills...")
        # minigame updates
        if self.minigames:
            allMinigames = "".join(self.minigames)
            logger.debug(f"created allMinigames...")
        # post updates
        if allSkills or allMinigames:
            fullMessage = f'**- {self.mentionMember} -**\n{allSkills}{allMinigames}'
            ### Add in code here later to work around Discord's 2k char limit ###
            await channel.send(fullMessage)
            if self.duplicateServerPost == False:
                logger.info(f"New update posted for {self.rsName} | Updates posted: {len(self.skills) + len(self.minigames)}:\n{fullMessage}")
        
        # We've now posted to our first server, others will be duplicates
        self.duplicateServerPost = True
        return


    # --- POST UPDATE(S) --- #
    def getMentionMember(self, member, server):
        if self.oldData['servers'][str(server.id)]['mention'] == True:
            self.mentionMember = member.mention
        else:
            self.mentionMember = member.name

    # --- BUILD ROLE MENTION STRING --- #
    # defaults to @here when no role specified
    def getMentionRole(self, rsRole):
        if rsRole == None:
            self.mentionRole = "@here"
        else:
            self.mentionRole = rsRole.mention

    # --- CHECK FOR UPDATES --- #
    def hasAnyUpdates(self):
        if self.skills or self.minigames or self.milestones:
            return True
        else:
            return False


    # ---------- UPDATE CREATION METHODS ------------ #

    # --- SKILLS --- #
    def updateSkill(self, newData, title, newEntry):
        logger.debug("in PlayerUpdate-updateSkill...")

        # skill was already on hiscores
        if not newEntry:  
            oldData = self.oldData['skills'][title]
            logger.debug(f"existing entry, old lvl: {oldData['level']}, new lvl: {newData['level']}...")
            xpNew = fs.formatInt(newData['xp'])
            xpOld = fs.formatInt(oldData['xp'])
            xpDiff = xpNew - xpOld
            logger.debug("calculated xp diff...")
            if newData['level'] != oldData['level']:  # check if level change
                logger.debug("difference in level...")
                # only add new Overall info below any skills updates
                if title == 'Overall':
                    self.makeOverallUpdate(oldData, newData)  # send to make method
                # updating skill that already exists on hiscores
                else: self.makeSkillUpdate(oldData, newData, title, xpDiff)
            else:  # xp gain, but no level change
                logger.debug(f"{title} had no lvl change, xp diff: {xpDiff}...")

            # check for any significant XP updates
            if xpNew >= 10000000:
                self.checkXpUpdate(oldData, newData, title, xpNew, xpOld, xpDiff)

        # skill is new to hiscores
        else:
            logger.debug("new entry...")
            message = f"**{self.rsName} levelled up {title} to {newData['level']}**\
                        ```This is the first time this skill is on the Hiscores```"
            self.skills.append(message)
            logger.debug(f"appended NEW update for {title} to skills list...")


    # --- MINIGAMES --- #
    def updateMinigame(self, newData, title, newEntry):
        logger.debug("in PlayerUpdate-updateMinigame...")

        # CLUES
        if 'Clue' in title:
            logger.debug("found clue...")
            clueLvl = clueSort(title)
            logger.debug(f"clue lvl: {clueLvl}...")

            if not newEntry:  # minigame was already on hiscores
                logger.debug("existing entry...")
                oldData = self.oldData['minigames'][title]
                countNew = fs.formatInt(newData['score'])
                countOld = fs.formatInt(oldData['score'])
                countDiff = countNew - countOld
                self.makeClueUpdate(oldData, newData, title, countNew, countOld, countDiff, clueLvl)

            else:  # minigame is new to hiscores
                logger.debug("new entry...")
                # all clue scrolls, get count
                if clueLvl == 'Total':
                    logger.debug(f"(all) clue found, count: {newData['score']}...")
                    self.clueAllTotal = fs.formatInt(newData['score'])
                    return
                # set correct usage of a/an
                if clueLvl in ['Easy', 'Elite']: an = 'an'
                else: an = 'a'
                # append total clues to message if total clues rank is on hiscores
                if self.clueAllTotal != None:
                    totalClueMsg = f" | Total clues completed: {fs.formatIntStr(self.clueAllTotal)}"
                else:
                    totalClueMsg = ""
                message = f"**{self.rsName} completed {an} {clueLvl} Clue Scroll for the first time**\
                            ```{clueLvl} clues completed: {fs.formatIntStr(newData['score'])} | Current rank: {newData['rank']}{totalClueMsg}```"
                self.minigames.append(message)
                logger.debug(f"appended update for {title} to minigames list...")

        # BOUNTY HUNTER
        elif 'Bounty Hunter' in title:
            # do BH sorting stuff
            return

        # BOSS
        else:
            logger.debug("found boss...")
            # change first word depending on boss/activity
            if title in nonMonsterBosses:  # not monsters
                if title == "Wintertodt":  # special case for wintertodt
                    action1 = 'subdued'
                    action2 = 'subdue'
                    logger.debug("nonmonster boss, wintertodt...")
                else:  # anything else not wintertodt
                    action1 = 'completed'
                    action2 = 'completion'
                    logger.debug("nonmonster boss...")
            else:  # any other boss will default to this
                action1 = 'killed'
                action2 = 'kill'
                logger.debug("monster boss...")

            if not newEntry:  # minigame was already on hiscores
                logger.debug("existing entry...")
                oldData = self.oldData['minigames'][title]
                killNew = fs.formatInt(newData['score'])
                killOld = fs.formatInt(oldData['score'])
                killDiff = killNew - killOld
                self.makeBossUpdate(oldData, newData, title, killNew, killOld, killDiff, action1, action2)

            else:  # minigame is new to hiscores
                logger.debug("new entry...")
                # check if this was a special boss
                if title in self.custom_messages['bosses']:
                    messageExtra = self.custom_messages['bosses'][title]
                    message = f"**{self.rsName} {action1} {title} for the first time! {messageExtra}**\
                                ```Total {action2} count: {fs.formatIntStr(newData['score'])} | Current rank: {newData['rank']}```"
                    self.milestones.append(message)
                    logger.debug(f"appended Boss update for {title} to milestones list...")
                else:
                    message = f"**{self.rsName} {action1} {title} for the first time**\
                                ```Total {action2} count: {fs.formatIntStr(newData['score'])} | Current rank: {newData['rank']}```"
                    self.minigames.append(message)
                    logger.debug(f"appended update for {title} to minigames list...")
            

    # ---------- MESSAGE & MILESTONE CHECKING METHODS ------------ #

    # --- OVERALL --- #
    def makeOverallUpdate(self, oldData, newData):
        logger.debug("assigning Overall...")
        lvlNew = fs.formatInt(newData['level'])
        lvlOld = fs.formatInt(oldData['level'])
        # MAX
        maxLvl = 2277
        if lvlNew == maxLvl and lvlOld != maxLvl:
            message = f"**{self.rsName} HAS ACHIEVED MAX TOTAL LEVEL {newData['level']}! DAMN SON**\
                        ```Overall XP: {newData['xp']} | Overall rank: {newData['rank']}```"
            self.milestones.append(message)
        # 2200 total
        elif lvlOld < 2200 and lvlNew >= 2200:
            message = f"**{self.rsName} has achieved 2,200 total level**\
                        ```Total level: {newData['level']} | Overall XP: {newData['xp']}```"
            self.milestones.append(message)
        # 2000 total
        elif lvlOld < 2000 and lvlNew >= 2000:
            message = f"**{self.rsName} has achieved 2,000 total level**\
                        ```Total level: {newData['level']} | Overall XP: {newData['xp']}```"
            self.milestones.append(message)
        # no milestones
        else: self.overallUpdate = f"```Total level: {newData['level']} | Total Overall XP: {newData['xp']}```"


    # --- SKILL --- #
    def makeSkillUpdate(self, oldData, newData, title, xpDiff):
        logger.debug(f"assigning {title}...")
        newLvl = newData['level']
        # special messages for 99
        if newLvl == '99':
            messageExtra = f". {self.custom_messages['max_levels'][title]}"
        # check for special messages
        elif newLvl in self.custom_messages['levels']:
            messageExtra = f". {self.custom_messages['levels'][newLvl]}"
        else: messageExtra = ''
        # make message
        message = f"**{self.rsName} levelled up {title} to {newLvl}{messageExtra}**\
                    ```{fs.formatIntStr(xpDiff)} XP gained | Total {title} XP: {newData['xp']}```"
        # 99 milestone
        if newLvl == '99':
            self.milestones.append(message)
            logger.debug(f"appended update for {title} to milestones list...")
        # any other level
        else:
            self.skills.append(message)
            logger.debug(f"appended update for {title} to skills list...")

    
    # --- XP UPDATE --- #
    def checkXpUpdate(self, oldData, newData, title, xpNew, xpOld, xpDiff):
        logger.debug(f"checking for xp milestones...")
        # check for overall or skill
        if title == 'Overall':
            threshold = 100000000  # 100 million
        else:
            threshold = 10000000  # 10 million
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while xpNew >= threshold:
            if xpOld < threshold:
                message = f"**{self.rsName} has achieved {fs.formatIntStr(threshold)} {title} XP**\
                            ```{fs.formatIntStr(xpDiff)} XP gained | Total {title} XP: {newData['xp']}```"
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


    # --- CLUE UPDATE --- #
    def makeClueUpdate(self, oldData, newData, title, countNew, countOld, countDiff, clueLvl):
        # check for clue milestones
        foundMilestone = False
        if clueLvl == 'Total':
            self.clueAllTotal = fs.formatInt(newData['score'])
            threshold = 250
        else:
            threshold = 100
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while countNew >= threshold:
            if countOld < threshold:
                if clueLvl != 'Total':  # show total if not already looking at total clues
                    messageExtra = f" | Total clues completed: {fs.formatIntStr(self.clueAllTotal)}"
                else: messageExtra = ""
                message = f"**{self.rsName} has completed at least {fs.formatIntStr(threshold)} {clueLvl} Clue Scrolls**\
                            ```{clueLvl} clues completed: {newData['score']} | Current rank: {newData['rank']}{messageExtra}```"
                self.milestones.append(message)
                logger.debug(f"appended Clue update for {title} to milestones list...")
                foundMilestone = True
                break
            else:
                threshold += increment
        # done with loop, check if posting regular update
        if not foundMilestone and clueLvl != 'Total':
            # set correct usage of plural (deprecated)
            # if countDiff == 1: s = ''
            # else: s = 's'
            logger.debug("found diff...")

            # append total clues to message if total clues rank is on hiscores
            if self.clueAllTotal != None:
                totalClueMsg = f" | Total clues completed: {fs.formatIntStr(self.clueAllTotal)}"
            else:
                totalClueMsg = ""
            message = f"**{self.rsName} has completed {newData['score']} {clueLvl} Clue Scrolls**\
                        ```New {clueLvl} clues logged: {countDiff} | Current rank: {newData['rank']}{totalClueMsg}```"

            self.minigames.append(message)
            logger.debug(f"appended update for {title} to minigames list...")
        logger.debug(f"done checking Clues...")


    # --- BOSS UPDATE --- #
    def makeBossUpdate(self, oldData, newData, title, killNew, killOld, killDiff, action1, action2):
        logger.debug(f"assigning Boss: {title}...")
        # check for boss milestones
        foundMilestone = False
        threshold = 500
        # loop thru intervals to see if a threshold has been passed
        increment = threshold
        while killNew >= threshold:
            if killOld < threshold:
                message = f"**{self.rsName} has {action1} {title} at least {fs.formatIntStr(threshold)} times**\
                            ```Total {action2} count: {newData['score']} | Current rank: {newData['rank']}```"
                self.milestones.append(message)
                logger.debug(f"appended Boss update for {title} to milestones list...")
                foundMilestone = True
                break
            else:
                threshold += increment
        # done with loop, check if posting regular update
        logger.debug("done checking loop...")
        if not foundMilestone:
            # set correct tense of time  --not needed anymore, flipped total/new counts - 7/4/20
            # if killDiff == 1: times = 'time'
            # else: times = 'times'
            logger.debug("found diff...")
            try:
                message = f"**{self.rsName} has {action1} {title} {newData['score']} times**```New {action2}s logged: {fs.formatIntStr(killDiff)} | Current rank: {newData['rank']}```"
            except Exception as e:
                logger.exception(f'Error posting boss update: {e}')
            logger.debug("made message...")
            self.minigames.append(message)
            logger.debug(f"appended update for {title} to minigames list...")
        logger.debug(f"done checking Bosses...")



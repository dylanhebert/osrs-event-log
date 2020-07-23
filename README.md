# Old School Runescape Activity Log - A Discord Bot

A simple Discord bot that captures and posts activity, events, and milestones for Old School Runescape players into a selected Discord channel.
- Default command prefix: **;**

## Setup
- Python Version: **3.8.5**
- Recommended: Set up **pyenv** in your machine's home directory
- Recommended: Set up **venv** with Python 3 using `python -m venv venv` in the root directory
- Create a bot on [Discord's dev page](https://discord.com/developers/applications) and make note of the token and invite URL
- Make a copy of *bot_config&#46;template&#46;json* and name it *bot_config&#46;json*
- In *bot_config&#46;json*, set the value of "BOT_TOKEN" to your Discord bot's token
- In *data/sotw*, make a copy of *sotw_config&#46;template&#46;json* and name it *sotw_config&#46;json*
- Run `pip install -r requirements.txt` to install dependencies
- Run `python main.py`
- After the bot starts, invite it to a server using the invite link
- OSRS player skills & milestones will be populated into *data/db_runescape&#46;json*
- Discord server & member/player data will be populated into *data/db_discord&#46;json*

## Commands
### **A**dmin Commands
```
posthere - Change the text channel where the bot posts
rsrole {@somerole} - A role to notify for milestone messages
resetrsrole - Defaults the milestone notify role to @here if not already
addother {@Discord-Member} {OSRS-Name} - Add someone to the Activity Log
removeother {@Discord-Member} {OSRS-Name} - Remove someone from the Activity Log
```
### **G**eneral Commands
```
add {OSRS-Name} - Join the Activity Log with your specified OSRS username
remove {OSRS-Name} - Remove one of your RS accounts from the current server in the Activity Log
togglemention {OSRS-Name} - Toggles whether or not to @ you on Discord for every update
transfer {OSRS-Name}>>{new-name} - Transfer/rename an account's info
myaccounts - List all RS accounts associated with you in this server
allaccounts - See a list of all players currently in the Activity Log
skillweek - Show all basic Skill of the Week information
skillweekhistory - Show all SOTW history for this server
```
### **S**uper Commands
```
sendannouncement {message} - Sends an message mentioning the RS role to every server
sendthought {message} - Sends a message to every server
changemaxplayers - Changes the amount of RS names a Discord member can be linked to
```

Thanks for the support!
# Old School Runescape Activity Log - A Discord Bot

A simple Discord bot that captures and posts activity, events, and milestones for Old School Runescape players into a selected Discord channel.
- Default command prefix: **;**

## Setup
- Create a bot on [Discord's dev page](https://discord.com/developers/applications) and make note of the token and invite URL
- Make a copy of *creds&#46;json* and name it *mycreds&#46;json*
- In *mycreds&#46;json*, set the value of "BOT_TOKEN" to your Discord bot's token
- Run *setup&#46;py*
- Run *main&#46;py*
- After the bot starts, invite it to a server using the invite link
- The server's info will be populated into *data/servers&#46;py*
- Players joining the event log will be populated into *data/players&#46;py*

## Commands
### **A**dmin Commands
```
posthere - Change the text channel where the bot posts
rsrole - <@somerole> | A role to notify for milestone messages
resetrsrole - Defaults the milestone notify role to @here if not already
add - <@Discord-Member> <OSRS-Name> | Add someone to the Activity Log
remove - <@Discord-Member> | Remove someone from the Activity Log
```
### **G**eneral Commands
```
join - <OSRS-Name> | Join the Activity Log
leave - Remove yourself from the Activity Log
togglemention - Toggles whether or not to @ you on Discord for every update
players - See a list of players currently in the Activity Log for that server
```
### **S**uper Commands
```
sendannouncement - Sends an announcement mentioning the RS role to every server & channel connected to this bot
sendthought - Sends a message to every server & channel connected to this bot
```

Thanks for the support!
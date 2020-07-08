# Old School Runescape Event Log - A Discord Bot

A simple Discord bot that captures and posts events and milestones for Old School Runescape players into a selected Discord channel.
- Default command prefix: ;

## Commands
```
join - <OSRS-Name> | Join the event log list
leave - Remove yourself from the event log list
togglemention - Toggles whether or not to @ you on discord for every update
players - See a list of players currently in the event log list
add - <@Discord-Member> <OSRS-Name> | Add someone to the event log list (admins only)
remove - <@Discord-Member> | Remove someone from the event log (admins only)
posthere - Add/Change the text channel where the bot posts (admins only)
rsrole - <@somerole> | A role to notify for special messages (admins only)
```

## Requirements
- discord.py
- feedparser
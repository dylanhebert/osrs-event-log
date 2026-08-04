# OSRS Activity Log Bot: web.py
# - The one command that connects Discord to the read-only web UI.
#
# This is a NEW cog rather than an addition to user.py on purpose. The web UI is
# a separate service on a separate port with a separate venv, and keeping its
# only bot-side code in its own file means the entire footprint of that project
# inside the live bot is this file plus one line in the extensions list.
#
# Modelled closely on ;dinklink in user.py, which has been issuing secrets over
# DM in production for a long time: generate, store, DM, catch Forbidden, and
# never echo the secret into a channel.

import discord
from discord.ext import commands

from common.logger import logger
from data import repo


class WebCommands(commands.Cog, name="Web UI"):

    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # Guild identity sync
    # ---------------------------------------------------------------- #
    # The database has never held guild names or icons: the bot always had
    # discord.Guild objects to hand, so it never needed them. The web UI has no
    # Discord connection at all, so without these it can only label a server by
    # an ordinal. These listeners keep servers.name and servers.icon_hash in
    # step, which is why the UI needs no hand-maintained id-to-name mapping and
    # why a rename shows up on its own.
    #
    # NOTE for anyone adding listeners elsewhere in this bot: a bare
    # `async def on_ready` inside a Cog is NEVER called. py-cord only registers
    # cog listeners that carry @commands.Cog.listener(). The undecorated
    # on_ready methods in user.py, admin.py and looper.py are dead code.

    @commands.Cog.listener()
    async def on_ready(self):
        logger.debug('WebCommands Cog Ready')
        await self.sync_guild_identities()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.sync_one(guild)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        # Fires on a rename or an icon change.
        self.sync_one(after)

    def sync_one(self, guild):
        """Best-effort. A failure here must never affect anything else."""
        try:
            icon = getattr(guild, 'icon', None)
            return repo.servers.sync_identity(
                guild.id, guild.name, getattr(icon, 'key', None))
        except Exception as e:
            logger.exception(f'could not sync guild identity for {guild.id} -- {e}')
            return False

    async def sync_guild_identities(self):
        """Refresh every known guild's name and icon.

        on_ready fires again after a reconnect, so this runs repeatedly. It is
        a handful of rows and sync_identity() skips the write when nothing has
        changed, so the steady-state cost is a few SELECTs.

        Wrapped so that a broken database can never stop the bot coming up.
        Names and icons are cosmetic; posting to Discord is not.
        """
        try:
            updated = 0
            for guild in self.bot.guilds:
                if self.sync_one(guild):
                    updated += 1
            if updated:
                logger.info(f'Guild identity sync updated {updated} server(s)')
            else:
                logger.debug('Guild identity sync: nothing changed')
        except Exception as e:
            logger.exception(f'guild identity sync failed -- {e}')

    @commands.command(  brief="Get a password for the web UI, sent by DM",
                        description="Sends you a password for the read-only web "
                                    "stats site.\n"
                                    "The password is DM'd to you and SHOULD BE KEPT SECRET.\n"
                                    "Using this command again issues a NEW password and "
                                    "retires the old one.\n"
                                    "Signing in shows you stats for everyone in the "
                                    "Discord servers you share with this bot.")
    @commands.cooldown(1, 30, commands.BucketType.user)
    @commands.guild_only()
    async def webpassword(self, ctx):
        member_id = ctx.author.id

        # Only members who actually have an account in the log get in. Without
        # this, anyone who can type in any server the bot is in could mint a
        # credential and read every player's stats.
        if not repo.webauth.is_known_member(member_id):
            return await ctx.send(
                "**You do not have any accounts in the Activity Log.** "
                "Add one with `;add <rs-name>` first, then try again.")

        try:
            password, issued_count = repo.webauth.issue(member_id)
        except Exception as e:
            logger.exception(f'{member_id}: could not issue a web password -- {e}')
            return await ctx.send('Error creating your password. Ask my creator.')

        again = ("\nYour previous password has stopped working."
                 if issued_count > 1 else "")

        try:
            await ctx.author.send(
                "Here is your password for the OSRS Event Log web UI:\n"
                f"```text\n{password}\n```"
                "It is shown once and is not stored anywhere I can read it back, "
                "so keep it somewhere safe. Run this command again if you lose it "
                "and I will issue a new one."
                f"{again}"
                "\nUse `;webrevoke` to switch it off entirely."
            )
        except discord.Forbidden:
            # The password has already been rotated at this point, so the old
            # one is dead either way. Say so rather than pretending nothing
            # happened, and never fall back to posting it in the channel.
            return await ctx.reply(
                "I couldn't DM you your password. Enable DMs from server members "
                "and run this again."
            )
        except Exception as e:
            logger.exception(f'{member_id}: could not DM a web password -- {e}')
            return await ctx.reply('Error sending your password. Ask my creator.')

        # Deliberately vague in-channel: confirming that a DM was sent is fine,
        # confirming anything about its contents is not.
        await ctx.reply("Sent you a DM with your web password.")
        logger.info(f'Issued a web password to member {member_id} '
                    f'(issue #{issued_count})')

    @commands.command(  brief="Stop your web UI password from working",
                        description="Deletes your web UI password. Anyone holding "
                                    "it can no longer sign in.\n"
                                    "Run ;webpassword to get a new one.")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def webrevoke(self, ctx):
        try:
            repo.webauth.revoke(ctx.author.id)
        except Exception as e:
            logger.exception(f'{ctx.author.id}: could not revoke web password -- {e}')
            return await ctx.send('Error revoking your password. Ask my creator.')
        await ctx.reply(
            "Your web password has been revoked. Anywhere you were signed in is "
            "signed out too. Run `;webpassword` when you want a new one.")
        logger.info(f'Revoked the web password for member {ctx.author.id}')


def setup(bot):
    bot.add_cog(WebCommands(bot))

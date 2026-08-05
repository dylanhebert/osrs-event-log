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
        await self.sync_member_identities()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.sync_one(guild)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        # Fires on a rename or an icon change.
        self.sync_one(after)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Nickname or avatar changed. Only members who already own an account
        # are recorded; everyone else in the guild is ignored.
        try:
            if repo.members.get(after.id) is not None:
                self.sync_member(after)
        except Exception as e:
            logger.exception(f'could not sync member {after.id} -- {e}')

    def sync_one(self, guild):
        """Best-effort. A failure here must never affect anything else."""
        try:
            icon = getattr(guild, 'icon', None)
            return repo.servers.sync_identity(
                guild.id, guild.name, getattr(icon, 'key', None))
        except Exception as e:
            logger.exception(f'could not sync guild identity for {guild.id} -- {e}')
            return False

    def sync_member(self, member):
        """Record one Discord member's name and avatar. Best-effort.

        THE GLOBAL NAME, NOT member.display_name.

        display_name is the per-server nickname when one is set, so the value
        stored depended on which guild this loop happened to reach last. Two
        servers with two nicknames meant the name on the site flipped between
        them for no reason a reader could see, and neither was the identity the
        person actually goes by everywhere.

        global_name is the account-wide display name. It is None on accounts
        that never set one and on older library versions, in which case
        repo.members falls back to the @handle, which is unique and always
        present.
        """
        try:
            avatar = getattr(member, 'avatar', None)
            return repo.members.sync(
                member.id,
                getattr(member, 'name', None),
                getattr(member, 'global_name', None),
                getattr(avatar, 'key', None))
        except Exception as e:
            logger.exception(f'could not sync member {member.id} -- {e}')
            return False

    async def sync_member_identities(self):
        """Record the name and avatar of everyone who owns an account.

        ONLY members already linked in player_servers. The bot can see every
        member of every guild it is in; storing all of them would mean holding
        profile data about people who have nothing to do with this log.

        Reads from the member cache rather than fetching, so it costs no API
        calls. A member the cache does not have is skipped and picked up on a
        later start.
        """
        try:
            wanted = set(repo.members.linked_member_ids())
            if not wanted:
                return
            updated = seen = 0
            for guild in self.bot.guilds:
                for member_id in list(wanted):
                    member = guild.get_member(member_id)
                    if member is None:
                        continue
                    seen += 1
                    wanted.discard(member_id)
                    if self.sync_member(member):
                        updated += 1
            if updated:
                logger.info(f'Member identity sync updated {updated} of {seen}')
            else:
                logger.debug(f'Member identity sync: nothing changed ({seen} seen)')
            if wanted:
                logger.debug(f'Member identity sync: {len(wanted)} not in cache')
        except Exception as e:
            logger.exception(f'member identity sync failed -- {e}')

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

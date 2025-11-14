# cogs/dink_webhook.py
import os
import json
from aiohttp import web
from discord.ext import commands
from common.logger import logger
import data.handlers as db
import dink_messages

# If you already have helpers for DB, import them here
# from data.handlers import get_discord_user_by_dink_hash, save_dink_event

class DinkWebhook(commands.Cog):
    """
    Runs a tiny HTTP server that receives Dink plugin webhooks and posts
    formatted messages into a Discord channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        # create the background task and run it in the background
        self.bot.bg_task = self.bot.loop.create_task(self.cog_load())

    async def cog_load(self):
        """Start the HTTP server when the cog is loaded."""

        logger.info('OSRS Event Log Dink webhook started!')
        port = db.get_dink_port()
        host = db.get_dink_host()
        
        app = web.Application()
        app["bot"] = self.bot

        # Per-player key; no global secret:
        # PATH/dink/<key>/webhook
        path = "/dink/{link_key}/webhook"
        app.router.add_post(path, self.handle_dink)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

        logger.info(f"[DinkWebhook] Listening on http://{host}:{port}{path}")

    async def cog_unload(self):
        """Cleanly stop the HTTP server when the cog is unloaded."""
        logger.info('Stopping OSRS Event Log Dink webhook...')
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    # HANDLE DINK
    async def handle_dink(self, request: web.Request) -> web.Response:
        """Main endpoint Dink posts to. Expects multipart with payload_json."""
        
        # 1) Validate the link key from the URL
        link_key = request.match_info.get("link_key")
        if not link_key:
            logger.warning("[DinkWebhook] Missing link_key in URL")
            return web.json_response({"error": "missing link key"}, status=400)
        logger.debug(f"[DinkWebhook] Received request for key={link_key} (start of handler)")

        valid_link = await db.is_dinklink_in_use(link_key)
        if not valid_link:
            logger.warning(f"[DinkWebhook] Invalid link_key={link_key}")
            return web.json_response({"error": "invalid link key"}, status=403)
        
        full_url = db.dink_link_full_url(link_key)
        
        # 2) Parse payload_json
        data = await request.post()
        payload_json = data.get("payload_json")
        if not payload_json:
            logger.warning(
                "[DinkWebhook] Missing payload_json in request. Full form: %r",
                dict(data),
            )
            return web.json_response({"error": "missing payload_json"}, status=400)

        # Log the raw JSON string from Dink
        # logger.debug("[DinkWebhook] Raw payload_json: %s", payload_json)

        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            logger.exception(
                "[DinkWebhook] invalid JSON in payload_json: %r", payload_json
            )
            return web.json_response({"error": "invalid JSON"}, status=400)

        # Pretty-print the parsed payload
        # logger.debug(
        #     "[DinkWebhook] Parsed payload:\n%s",
        #     json.dumps(payload, indent=2, sort_keys=True),
        # )

        payload["_dink_link"] = full_url
        payload["_dink_link_key"] = link_key

        # Optional: log screenshot meta if present (but not bytes)
        file = data.get("file")
        if file is not None:
            logger.debug(
                "[DinkWebhook] Screenshot upload: filename=%s, content_type=%s, size=%s",
                getattr(file, "filename", None),
                getattr(file, "content_type", None),
                getattr(file, "size", None),
            )

        await self.dispatch_dink_event(payload)
        return web.json_response({"ok": True})

    # DISPATCH
    async def dispatch_dink_event(self, payload: dict):
        """Convert Dink payload into a message or DB event."""
        channel_id = db.get_dink_test_channel()
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.info("[DinkWebhook] Channel not found")
            return

        message = self.format_dink_message(payload)
        # TODO: hook into posting in correct channels
        if message:
            await channel.send(message)

    # FORMAT MESSAGE
    def format_dink_message(self, payload: dict) -> str:
        rsn = payload.get("playerName")
        dink_hash = payload.get("dinkAccountHash")
        user_tag = rsn  # placeholder

        # TODO: hook into normal mentioning of users like normal messages

        return dink_messages.format_dink_message(payload, user_tag)


def setup(bot: commands.Bot):
    bot.add_cog(DinkWebhook(bot))

import discord
from discord.ext import commands
import os
import asyncpg
import logging
from dotenv import load_dotenv
from database import DatabaseManager

# --- SETUP LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
GUILD_ID = int(os.getenv("GUILD_ID"))
MY_GUILD = discord.Object(id=GUILD_ID)

class LogisticsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = None # Will hold DatabaseManager

    async def setup_hook(self):
        # 1. Init Database
        pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=10, statement_cache_size=0)
        self.db = DatabaseManager(pool)
        logger.info("Database connected.")

        # 2. Load Cogs
        await self.load_extension("src.cogs.members")
        await self.load_extension("src.cogs.logistics")
        await self.load_extension("src.cogs.admin")
        logger.info("Cogs loaded.")

        # 3. Sync Commands
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info(f"Commands synced to Guild {GUILD_ID}")

    async def on_ready(self):
        logger.info(f'Logged in as {self.user}')

bot = LogisticsBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("⛔ Permission Denied.", ephemeral=True)
    else:
        logger.error(f"Command Error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Internal Error.", ephemeral=True)

bot.run(DISCORD_TOKEN)
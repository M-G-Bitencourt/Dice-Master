import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.db_functions import get_character_profile
from utils.db_functions import get_character_resources

class Sheet(commands.Cog):
    """

    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")



async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))
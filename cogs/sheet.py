import discord
from discord import app_commands
from discord.ext import commands

class Sheet(commands.Cog):
    """

    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot




async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))
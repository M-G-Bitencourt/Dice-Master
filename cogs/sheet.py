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

    # sheet ---------------------------------------------------
    @app_commands.command(
        name="sheet",
        description="Envia sua ficha de personagem no chat como uma mensagem efêmera"
    )
    async def sheet(self, interaction: discord.Interaction,):
        
        player_id = interaction.user.id
        character = get_character_profile(self.db_connection, player_id)

        name = character["name"]
        # Basic Atributes
        st = character["st"]
        dx = character["dx"]
        iq = character["iq"]
        ht = character["ht"]
        er = character["energy_reserve"]
        # secondary characteristics
        max_pv = int(st) + int(character["additional_max_pv"])
        max_pf = int(ht) + int(character["additional_max_pf"])
        vont = int(iq) +int(character["additional_vont"])
        per = int(iq) + int(character["additional_per"])

        # Other Stats
        character_resource = get_character_resources(self.db_connection, player_id)

        character_resource_str = "".join(
            f"**{resource_name.upper()}:** `{resource_value}`\n" 
            for resource_name, resource_value in character_resource.items()
        )

        sheet_embed = discord.Embed(title=f"**{name}**")
        sheet_embed.color = discord.Color.gold()

        sheet_embed.add_field(
            name="Atributos Básicos",
            value=(
                f"**ST:** `{st}`\n"
                f"**DX:** `{dx}`\n"
                f"**IQ:** `{iq}`\n"
                f"**HT:** `{ht}`\n"
                f"**ER:** `{er}`"
            ),
            inline=False
        )

        sheet_embed.add_field(
            name="Características Secundárias",
            value=(
                f"PV Máximo: `{max_pv}`\n"
                f"PF Máximo: `{max_pf}`\n"
                f"Vontade: `{vont}`\n"
                f"Percepção: `{per}`\n"
            ),
            inline=False
        )

        sheet_embed.add_field(
            name="PV - PF - ER",
            value=character_resource_str,
            inline=False
        )
        

        await interaction.response.send_message(embed=sheet_embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))
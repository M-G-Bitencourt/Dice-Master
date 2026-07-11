import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.db_functions import get_character_profile

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
    async def sheet(self, interaction: discord.Interaction):
        # Immediate deferral to respect Discord's temporal strictures.
        await interaction.response.defer(ephemeral=True)
        
        player_id = interaction.user.id
        
        try:
            character = get_character_profile(self.db_connection, player_id)
        except ValueError as e:
            # Capturing database anomalies if the user lacks an active character matrix
            await interaction.followup.send(f"Erro de processamento: {e}", ephemeral=True)
            return

        name = character["name"]
        
        # Basic Attributes
        st = character["st"]
        dx = character["dx"]
        iq = character["iq"]
        ht = character["ht"]
        base_er = character["energy_reserve"]
        
        # Secondary Characteristics
        max_pv = int(st) + int(character["additional_max_pv"])
        max_pf = int(ht) + int(character["additional_max_pf"])
        vont = int(iq) + int(character["additional_vont"])
        per = int(iq) + int(character["additional_per"])

        # Volatile Resources extracted directly from the denormalized foundational matrix
        current_pv = character["current_pv"]
        current_pf = character["current_pf"]
        current_er = character["current_er"]

        sheet_embed = discord.Embed(title=f"**{name}**", color=discord.Color.gold())

        sheet_embed.add_field(
            name="Atributos Básicos",
            value=(
                f"**ST:** `{st}`\n"
                f"**DX:** `{dx}`\n"
                f"**IQ:** `{iq}`\n"
                f"**HT:** `{ht}`\n"
                f"**ER:** `{base_er}`"
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

        # Inline formatting, completely eradicating the superfluous intermediate variable
        sheet_embed.add_field(
            name="Recursos Atuais (PV - PF - ER)",
            value=(
                f"**PV:** `{current_pv}`\n"
                f"**PF:** `{current_pf}`\n"
                f"**ER:** `{current_er}`"
            ),
            inline=False
        )
        
        # Mandatory followup via webhook, transmitting the final embed
        await interaction.followup.send(embed=sheet_embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))
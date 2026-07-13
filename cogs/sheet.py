import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.db_functions import get_character_profile
from utils.db_functions import get_character_thumbnail_payload
from utils.db_functions import get_character_thumbnail_by_id
from utils.db_functions import get_character_profile_by_id

class Sheet(commands.Cog):
    """

    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        Dynamically queries the database for characters matching the user's keystrokes.
        Limits the return pool to 25 instances, respecting Discord API constraints.
        """
        cursor = self.db_connection.cursor()
        
        # SQL Injection defensive parameterization with wildcard
        search_pattern = f"%{current}%"
        
        cursor.execute(
            """
            SELECT character_id, name 
            FROM characters 
            WHERE name LIKE ? 
            LIMIT 25
            """,
            (search_pattern,)
        )
        
        fetched_characters = cursor.fetchall()
        
        return [
            app_commands.Choice(name=row[1], value=str(row[0]))
            for row in fetched_characters
        ]

    
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

        # Volatile Resources
        current_pv = character["current_pv"]
        current_pf = character["current_pf"]
        current_er = character["current_er"]

        # Points
        current_points = character["current_points"]
        total_points = character["total_points"]

        # Money
        money = character["money"]

        sheet_embed = discord.Embed(title=f"**{name}**", color=discord.Color.gold(), description=f"**Total de Pontos:** `{total_points}`\n**Pontos não Gastos:** `{current_points}`\n**Dinheiro:** `{money}`")

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
        # images
        character_file, thumbnail_url = get_character_thumbnail_payload(self.db_connection, player_id)

        if thumbnail_url:
            sheet_embed.set_thumbnail(url=thumbnail_url)

        # Mandatory followup via webhook, transmitting the final embed
        await interaction.followup.send(embed=sheet_embed, file=character_file, ephemeral=True)


    @app_commands.command(
        name="sheet_view",
        description="Permite ao mestre inspecionar a matriz completa de qualquer personagem no sistema."
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(character="A entidade que será submetida à inspeção estrutural")
    @app_commands.default_permissions(administrator=True)
    async def sheet_view(
        self, 
        interaction: discord.Interaction, 
        character: str
    ):
        # Immediate deferral to respect Discord's temporal strictures.
        # Set to False to permit the Master to render the diagnostic metrics to the channel.
        await interaction.response.defer(ephemeral=True)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                "Erro de processamento: O identificador do personagem fornecido é estruturalmente inválido."
            )
            return

        # Invoking the newly minted high-efficiency primary key extraction function
        try:
            character_data = get_character_profile_by_id(self.db_connection, target_character_id)
        except ValueError as e:
            await interaction.followup.send(f"Erro de processamento: {e}")
            return

        
        name = character_data["name"]

        # Basic Attributes
        st = character_data["st"]
        dx = character_data["dx"]
        iq = character_data["iq"]
        ht = character_data["ht"]
        base_er = character_data["energy_reserve"]


        # Secondary Characteristics calculation (Algebraic evaluation)
        max_pv = st + character_data["additional_max_pv"]
        max_pf = ht + character_data["additional_max_pf"]
        vont = iq + character_data["additional_vont"]
        per = iq + character_data["additional_per"]

        current_pv = character_data["current_pv"]
        current_pf = character_data["current_pf"]
        current_er = character_data["current_er"]

        # Points
        current_points = character_data["current_points"]
        total_points = character_data["total_points"]

        # Money
        money = character_data["money"]

        # Embed Construction Pipeline
        sheet_view_embed = discord.Embed(
            title=f"**{name}**", 
            description=f"**Total de Pontos:** `{total_points}`\n**Pontos não Gastos:** `{current_points}`\n**Dinheiro:** `{money}`",
            color=discord.Color.gold()
        )

        sheet_view_embed.add_field(
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

        sheet_view_embed.add_field(
            name="Características Secundárias",
            value=(
                f"PV Máximo: `{max_pv}`\n"
                f"PF Máximo: `{max_pf}`\n"
                f"Vontade: `{vont}`\n"
                f"Percepção: `{per}`\n"
            ),
            inline=False
        )

        # Presentation of Current Resources mapped against their absolute maximums
        sheet_view_embed.add_field(
            name="Recursos Atuais (PV - PF - ER)",
            value=(
                f"**PV:** `{current_pv}`\n"
                f"**PF:** `{current_pf}`\n"
                f"**ER:** `{current_er}`"
            ),
            inline=False
        )
        
        # Binary asset pipeline extraction using the primary key
        character_file, thumbnail_url = get_character_thumbnail_by_id(self.db_connection, target_character_id)

        if thumbnail_url:
            sheet_view_embed.set_thumbnail(url=thumbnail_url)

        # Strict conditional dispatch protecting network payload against NoneType serialization
        # Slipped to match the ephemeral=False definition established in the deferral phase
        if character_file is not None:
            await interaction.followup.send(embed=sheet_view_embed, file=character_file, ephemeral=True)
        else:
            await interaction.followup.send(embed=sheet_view_embed,ephemeral=True)

async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))